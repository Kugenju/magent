# 阶段文档汇总

## 完成情况

根据当前路线图与各阶段记录：

| 阶段 | 状态 |
|---|---|
| 1–8 | 已完成 |
| 9 | 候选发布收口已完成；正式 release 仍需远程 CI 与维护者确认 |

以下按阶段顺序保留原计划、实施记录与验收标准。阶段状态以各阶段记录和 [路线图](ROADMAP.md) 为准。


<a id="phase-doc-phase1"></a>

## 原文：PHASE1.md

### 阶段 1：Agent、State 与 Result 最小执行模型
#### 1. 阶段目标
实现自研多智能体框架的第一个稳定内核，回答三个问题：

1. Agent 如何被统一描述和调用？
2. Agent 如何读取状态并返回状态更新？
3. 框架如何在一次运行中按确定顺序执行多个 Agent，并记录结果？

本阶段的目标是稳定公共 API 和执行语义，不追求功能数量。实现应保持本地单进程、异步兼容、确定性和可测试。

#### 2. 明确不做的内容
本阶段禁止提前加入以下功能：

- 有向 Graph、条件路由和循环
- 并行执行和 EventBus
- SQLite Checkpoint、进程恢复和分布式执行
- 真实 NVD/CNVD 请求
- LLM、Prompt、工具调用
- VulnTell 数据模型和业务数据库
- 复杂插件发现机制

这些功能会在后续阶段基于本阶段 API 增加。不要为了“未来可能使用”提前设计大量抽象。

#### 3. 建议实现范围
##### 3.1 包结构
```text
src/magent/
├── __init__.py
└── core/
    ├── __init__.py
    ├── agent.py       # Agent 协议或抽象基类
    ├── state.py       # State 类型约束与状态更新
    ├── result.py      # AgentResult 和执行状态
    ├── runtime.py     # 单次运行上下文
    ├── executor.py    # 阶段 1 顺序执行器
    └── errors.py      # 框架异常
tests/
└── unit/
    ├── test_agent.py
    ├── test_state.py
    ├── test_result.py
    └── test_executor.py
```

##### 3.2 Agent 协议
推荐使用 `Protocol` 或小型抽象基类定义稳定协议：

```python
class Agent(Protocol):
    name: str

    async def run(self, state: State, runtime: Runtime) -> AgentResult:
        ...
```

要求：

- `name` 在一次执行图或 pipeline 中唯一
- `run()` 统一为异步调用；同步函数由后续适配层处理
- Agent 读取输入状态，通过 `AgentResult` 返回更新
- Agent 不直接修改框架持有的原始状态对象
- Agent 不依赖 `examples.vulntell`

可以保留 `role` 作为展示元数据，但它不应参与调度或业务判断。

##### 3.3 State 与 StateUpdate
阶段 1 需要一个最小的、可复制的状态容器。推荐：

- 使用 Pydantic `BaseModel` 作为示例状态类型
- 执行器把状态传给 Agent 前进行校验
- Agent 返回部分更新，而不是直接写共享字典
- 更新合并后生成新状态或明确的不可变快照
- 更新字段未知、类型不符或合并冲突时抛出框架异常

不要在阶段 1 强行规定所有业务都使用同一个 State 类。框架应支持用户定义自己的 Pydantic 状态模型。

最小示例：

```python
class DemoState(BaseModel):
    value: int = 0
    messages: list[str] = Field(default_factory=list)
```

列表默认值必须使用 `default_factory`，不得使用可变默认参数。

##### 3.4 AgentResult
建议至少包含：

```text
status: success | skipped | failed
updates: 状态部分更新
message: 可选说明
error: 可选结构化错误
metadata: 执行元数据
```

阶段 1 的 Agent 异常可以由执行器统一捕获并转换为失败结果，但必须保留原始异常类型、Agent 名称和运行 ID。是否自动重试留到阶段 4，不要在本阶段隐式重试。

##### 3.5 Runtime
阶段 1 只实现不可变或只读运行上下文：

- `run_id`
- 当前 Agent 名称
- 开始时间
- 日志接口或最小 logger

`run_id` 应由框架生成，也允许测试传入固定值。不要在 Runtime 中提前塞入重试、Checkpoint、工具和 LLM 配置，除非它们已有明确行为。

##### 3.6 顺序执行器
实现一个明确命名的 `SequentialExecutor` 或 `PipelineExecutor`，接收 Agent 列表并按注册顺序执行：

```text
初始 State
  ↓
Agent A → 合并 updates
  ↓
Agent B → 合并 updates
  ↓
最终 State + ExecutionReport
```

阶段 1 的默认错误策略建议为 fail-fast：任一 Agent 返回 failed 或抛出异常，停止后续 Agent，并在报告中标识已完成、当前失败和未执行节点。跳过、降级和继续执行属于后续策略。

执行报告至少记录：

- `run_id`
- 初始和最终状态
- 每个 Agent 的顺序
- 每个 Agent 的状态
- 开始/结束时间或耗时
- 失败 Agent 和错误摘要

#### 4. 实现注意事项
##### API 与边界
- 统一使用 `async def`，执行器通过 `await agent.run(...)` 调用
- 框架核心不得导入漏洞模型、httpx、数据库驱动或 LLM SDK
- 不要让 Agent 直接持有执行器内部可变状态
- 不要把日志文本当作 Agent 之间的数据协议
- 不要用 `print()` 作为框架核心的观测机制
- 公共对象应提供类型标注和简短 docstring

##### 状态安全
- 状态字段应可序列化，为阶段 5 的快照做准备
- Pydantic 模型的可变列表和字典使用 `default_factory`
- 明确更新是浅合并还是字段级替换
- 阶段 1 遇到同一字段重复更新时应采用明确策略：拒绝或后写覆盖；必须写测试
- 不要默认进行深度智能合并

##### 错误处理
- 区分 Agent 业务失败和框架执行失败
- 错误信息不能泄漏 API Key 或完整敏感输入
- 不自动吞异常，也不使用裸 `except:`
- 失败报告要能区分“未执行”和“执行失败”
- 不实现隐式重试，避免后续无法统计真实执行次数

##### 测试隔离
- 阶段 1 测试不能访问网络、文件系统或真实数据库
- 使用 Dummy Agent 和固定状态验证执行语义
- 测试异步 Agent、同步错误、非法状态更新和重复 Agent 名称
- 时间测试不要依赖精确墙钟值；使用可注入 clock 或只断言耗时非负

#### 5. 推荐任务拆分
##### Task 1：定义公共类型
实现 Agent、State 约定、AgentResult、ExecutionStatus、Runtime 和框架异常。补充 API docstring 和类型检查。

##### Task 2：实现状态校验与更新合并
支持用户定义 Pydantic State，验证部分更新、未知字段、类型错误和重复字段策略。

##### Task 3：实现顺序执行器
支持按列表执行 Agent、生成 `run_id`、收集执行报告和默认 fail-fast。

##### Task 4：编写单元测试
覆盖成功链路、Agent 异常、failed 结果、非法更新、重复名称、空列表和执行报告。

##### Task 5：编写最小示例
实现 `ProducerAgent` 和 `ConsumerAgent`：Producer 将固定值写入状态，Consumer 读取并生成确认信息。示例必须完全离线、可重复运行。

##### Task 6：整理文档与提交
补充 README 的最小使用示例、API 说明和阶段记录，提交信息建议为 `feat(core): add minimal agent state executor`。

#### 6. 验收标准
##### 功能验收
- [ ] 能定义至少两个不依赖业务的 Dummy Agent
- [ ] 执行器按注册顺序调用 Agent
- [ ] 前一个 Agent 的状态更新可被后一个 Agent 读取
- [ ] 最终结果包含最终 State 和 ExecutionReport
- [ ] 空 Agent 列表有明确且有测试覆盖的行为
- [ ] Agent 名称重复时在执行前报错

##### 错误验收
- [ ] Agent 抛出异常时，执行器返回或抛出统一框架错误
- [ ] 失败 Agent 后续节点不会执行
- [ ] 报告区分成功、失败和未执行
- [ ] 非法状态字段或类型更新不能静默通过
- [ ] 阶段 1 不发生自动重试

##### 质量验收
- [ ] `python -m pytest` 全部通过
- [ ] 测试不访问网络和真实外部服务
- [ ] `import magent` 成功
- [ ] 核心代码有类型标注和必要 docstring
- [ ] 核心依赖不包含业务层依赖
- [ ] README 能让新用户在几分钟内运行 Producer/Consumer 示例

#### 7. 阶段完成后的输出
阶段结束时应得到：

```text
可导入的 magent 包
可复用的 Agent / State / Result / Runtime API
确定性的顺序执行器
结构化执行报告
完整单元测试
离线 Producer/Consumer 示例
阶段 1 API 文档和提交记录
```

完成这些内容后，才进入阶段 2 的 Graph 和条件执行设计。下游 Agent 不应在本阶段擅自扩展到并发、Checkpoint 或 VulnTell。


<a id="phase-doc-phase2"></a>

## 原文：PHASE2.md

### 阶段 2：Graph 与顺序、条件执行
#### 1. 当前基线
阶段 1 已完成最小执行内核：

- 提交：`70c08e9`
- 测试：17 个测试通过
- 已有能力：`BaseAgent`、Pydantic 状态更新、`AgentResult`、`Runtime`、`SequentialExecutor`、结构化执行报告
- 已验证：Producer/Consumer 离线示例、fail-fast、非法更新检测、重复 Agent 名称检测

阶段 2 应在现有 API 上增量实现，不能通过重写阶段 1 来实现 Graph。`SequentialExecutor` 仍需保持可用。

当前实现状态：Graph 相关代码已经存在于工作区，阶段 1 与阶段 2 测试共 39 个并全部通过，但阶段 2 尚未完成正式验收。进入阶段 3 前必须完成本文件第 3 节的收口项，并形成独立提交。

#### 2. 阶段目标
将当前“Agent 列表顺序执行”扩展为“可校验的有向执行图”，支持：

1. 节点注册和唯一节点 ID
2. 无条件边
3. 基于状态的条件路由
4. Graph 编译期校验
5. 图上的单进程顺序执行
6. 与阶段 1 相同的状态更新、错误和执行报告语义

本阶段的核心产出不是并发，而是明确、可测试、可扩展的图拓扑和路由语义。

#### 3. 进入条件：先完成阶段 1 工程收口
开始 Graph 代码前，应先完成以下小修正：

- [x] `ExecutionReport.steps` 等集合字段使用 `Field(default_factory=...)`
- [x] 冲突更新检查具有原子性：发现冲突时不能只记录部分字段后再失败
- [x] Runtime 的耗时计算使用与 Executor 一致的可注入 clock
- [x] 补充成功、跳过、显式失败和非法更新的断言
- [x] 确认阶段 1 公共 API 不依赖 VulnTell、网络、数据库或 LLM
- [x] 补充 `../architecture/API.md` 中对阶段 1 公共 API 的说明
- [ ] 修复 `CompiledGraph` 对外暴露可变字典的问题
- [ ] 修复条件分支和 router 失败时的重复 `StepRecord`
- [ ] 导出并测试阶段 2 的顶层公共 API
- [ ] 增加报告中节点记录唯一性的回归测试

这些修正不得改变阶段 1 的默认策略：顺序执行、fail-fast、无隐式重试。

#### 4. 范围与非目标
##### 本阶段包含
- `GraphBuilder` 或等价的可变构建器
- 编译后的不可变 Graph
- 节点、无条件边、条件边和 `END` 终点
- 顺序 `GraphExecutor`
- Graph 结构校验
- 路由和执行测试

##### 本阶段不包含
- 并行执行、fan-out/fan-in
- 循环和自引用边
- EventBus
- 重试、超时和取消策略
- Checkpoint 和持久化
- LLM、工具调用和自主规划
- VulnTell 业务 Agent

并行执行需要状态 reducer 和冲突策略，循环执行需要最大步数、恢复和取消语义，应分别放到后续阶段。

#### 5. 推荐的公共 API
以下 API 是实现建议。下游 Agent 可以调整命名，但必须保持相同语义，并在 `../architecture/API.md` 记录最终版本。

```python
END = "__end__"

graph = GraphBuilder()
graph.add_node("start", StartAgent("start"))
graph.add_node("review", ReviewAgent("review"))
graph.add_node("publish", PublishAgent("publish"))
graph.set_entry_point("start")
graph.add_edge("start", "review")
graph.add_conditional_edges(
    "review",
    route_review,
    {"approved": "publish", "rejected": END},
)
compiled = graph.compile()

state, report = await compiled.run(initial_state)
```

##### API 语义
- `node_id` 是 Graph 内部唯一标识，可以与 `agent.name` 不同
- `add_node()` 只注册节点，不执行 Agent
- `set_entry_point()` 只能设置一个入口
- `add_edge(source, target)` 表示唯一确定的下一节点
- `add_conditional_edges(source, router, mapping)` 由 `router(state)` 返回 label，再通过 mapping 选择目标
- 目标可以是已注册节点或 `END`
- `compile()` 返回不可变的编译结果；编译后不能修改拓扑
- `run()` 使用阶段 1 的 `State`、`AgentResult`、`Runtime` 和 `merge_updates`

阶段 2 的 router 在 Agent 状态更新合并成功后调用，因此可以读取最新状态。router 只能返回合法 label，不得直接修改状态。

#### 6. 图执行语义
##### 6.1 顺序执行
```text
入口节点
   ↓
执行 Agent
   ↓
校验并合并 AgentResult.updates
   ↓
选择下一条边
   ↓
直到 END
```

每个运行实例只沿一条路径执行。没有被选中的分支不执行，不应被误记为成功。

##### 6.2 节点出边规则
阶段 2 为保持语义简单，单个节点只能具有以下两种出边形式之一：

- 一条无条件边
- 一组条件边和一个 router

不能同时配置无条件边与条件边，也不能配置多条无条件边。多个后继节点将在阶段 3 并发执行中定义。

##### 6.3 终点规则
建议所有正常终点显式指向 `END`。编译器应拒绝没有明确终点的可达路径，避免执行器因“没有下一节点”而产生不一致行为。

##### 6.4 失败规则
沿用阶段 1 的 fail-fast：

- Agent 抛出异常：记录结构化 AgentError，停止执行
- Agent 返回 `FAILED`：记录失败结果，停止执行
- 状态更新非法：记录 StateUpdateError，停止执行
- router 抛出异常或返回未知 label：记录路由错误，停止执行
- 不进行自动重试

#### 7. 编译期校验
`compile()` 至少应检查：

- [ ] 节点 ID 非空且唯一
- [ ] 入口已设置且存在
- [ ] 边的 source 存在
- [ ] 边的 target 存在或等于 `END`
- [ ] 条件 mapping 的 label 非空且不重复
- [ ] 条件 mapping 的 target 合法
- [ ] 节点没有同时配置无条件边和条件边
- [ ] 不存在多条无条件边
- [ ] 不存在循环或自引用边
- [ ] 所有注册节点都从入口可达
- [ ] 每条可达路径最终都能到达 `END`

建议使用独立的 `GraphValidationError`，错误中包含 source、target 或 node_id，便于下游排查。

编译结果应保存规范化后的节点和边信息，避免执行期间继续读取构建器的可变内部结构。

#### 8. 执行报告设计
优先复用阶段 1 的 `StepRecord` 和 `ExecutionReport`，保持已有调用方兼容：

- `StepRecord.order` 表示实际访问顺序
- `StepRecord.agent_name` 保留 Agent 名称
- 如果需要展示 Graph 节点，新增可选 `node_id` 字段，不删除已有字段
- 报告应能区分已访问节点、失败节点和未访问分支
- 最终状态只包含成功合并的更新

如果新增 `execution_mode`、`graph_name` 等字段，必须提供默认值，不能破坏阶段 1 的报告反序列化。

#### 9. 推荐实现结构
```text
src/magent/graph/
├── __init__.py
├── builder.py       # GraphBuilder、节点和边注册
├── model.py         # 编译后的 Graph、END、路由类型
├── validator.py     # compile-time 校验
└── executor.py      # 单进程顺序 GraphExecutor
tests/unit/
├── test_graph_builder.py
├── test_graph_validation.py
└── test_graph_executor.py
```

如果实现规模较小，可以先使用一个 `graph.py` 文件，但公共类型、校验和执行逻辑仍应保持职责分离。

#### 10. 任务拆分
##### Task 1：阶段 1 工程收口
修复集合默认值、冲突更新原子性和 Runtime clock 一致性，补充相应回归测试。不得引入 Graph 依赖。

##### Task 2：Graph 数据结构
实现节点、边、入口和 `END` 表达。构建器应允许逐步添加拓扑，但不在添加时执行 Agent。

##### Task 3：Graph 编译校验
实现节点/边存在性、出边规则、可达性、环检测和终点检测。所有校验错误使用明确异常类型。

##### Task 4：无条件图执行
实现 A→B→C→END，复用阶段 1 的状态合并、报告和 fail-fast 行为。

##### Task 5：条件路由
实现 router、label mapping、B/C 分支和 END 分支，验证 router 读取的是更新后的状态。

##### Task 6：兼容性与文档
确保旧的 `SequentialExecutor` 测试继续通过；更新 `README.md` 或 `../architecture/API.md`，添加最小 Graph 示例和当前限制。

#### 11. 测试要求
至少覆盖以下场景：

##### 构建和校验
- [ ] 空 Graph 编译失败
- [ ] 未设置入口编译失败
- [ ] 重复节点失败
- [ ] 未知 source/target 失败
- [ ] 节点不可达失败
- [ ] 存在环失败
- [ ] 同时配置无条件边和条件边失败
- [ ] 多条无条件边失败
- [ ] 缺少 `END` 的路径失败

##### 执行和路由
- [ ] A→B→C→END 按正确顺序执行
- [ ] 条件为 true 时只执行 B 分支
- [ ] 条件为 false 时只执行 C 或 END 分支
- [ ] router 可以读取前一节点更新后的状态
- [ ] 未选分支不会执行或产生副作用
- [ ] Agent 更新可传递到后续节点
- [ ] Agent 失败后停止后续路径
- [ ] router 失败或返回未知 label 时结构化失败
- [ ] 最终报告包含实际路径和最终状态

##### 兼容性和质量
- [ ] 阶段 1 的原有 17 个测试继续通过
- [ ] 阶段 2 新增不少于 12 个有意义的测试
- [ ] 测试不访问网络、数据库或 LLM
- [ ] Graph 编译后修改 Builder 不影响已编译 Graph
- [ ] `import magent` 和离线示例继续成功

#### 12. 完成定义
阶段 2 只有在以下条件全部满足后才算完成：

```text
阶段 1 收口项完成
        ↓
Graph 可构建、可编译、可校验
        ↓
无条件路径和条件分支可执行
        ↓
失败和路由错误语义明确
        ↓
原有 API 与测试不回归
        ↓
API 文档和限制说明完成
```

完成后再进入阶段 3 的并发和 EventBus 设计。阶段 2 不应为了演示而提前实现并行、重试、Checkpoint 或 VulnTell。

#### 13. 建议提交
```text
fix(core): close phase-1 execution semantics
feat(graph): add graph builder and compiled topology
feat(graph): add graph validation
feat(graph): add sequential graph executor
feat(graph): add conditional routing
test(graph): cover validation and execution paths
docs: document phase-2 graph API
```


<a id="phase-doc-phase3"></a>

## 原文：PHASE3.md

### 阶段 3：并发执行与 EventBus
#### 1. 当前状态
阶段 3 的主要功能已经实现并完成发布：fan-out/fan-in、状态 reducer、最大并发限制、失败时的兄弟分支取消和进程内 EventBus。阶段 4 回归后当前工作区共有 103 个离线测试，全部通过。

阶段 3 的能力已被阶段 4 的可靠性 runner 和结构化尝试报告复用；本文件保留阶段 3 的拓扑和并发语义，后续 checkpoint 语义见 [`PHASE5.md`](PHASES.md#phase-doc-phase5)。

#### 2. 阶段目标与范围
本阶段在阶段 2 的单路径 Graph 上增加：

- 无依赖节点的并发执行
- 显式 fan-out/fan-in 拓扑
- 分支状态隔离和 join 合并
- 显式 reducer 与并发冲突检测
- 最大并发数限制
- 失败时的兄弟任务取消和资源清理
- 进程内、内存型 EventBus
- 并发执行报告和峰值并发统计

本阶段不包含重试、节点超时、Checkpoint、进程恢复、分布式执行、循环图、动态规划、LLM 或 VulnTell 业务。

#### 3. 并发 Graph 语义
```text
        ┌→ B ─┐
A ──────┤     ├→ D
        └→ C ─┘
```

执行规则：

1. A 成功后生成一个稳定状态快照。
2. B 和 C 从同一快照启动，不能直接修改彼此状态。
3. 分支通过 `AgentResult` 提交部分更新。
4. D 等待所有必需分支完成并成功后执行。
5. 分支更新在 join 处按声明顺序合并，不使用 asyncio 完成顺序。

推荐使用显式 API：

```python
graph.add_parallel_edges("a", ["b", "c"])
graph.add_join("d", parents=["b", "c"])
```

`add_edge()` 仍然表示单个无条件后继；条件边仍然只选择一个目标。

#### 4. 状态合并
- 不同字段可以自动合并。
- 同一字段被多个分支更新时，没有 reducer 就抛出 `StateMergeConflictError`。
- 需要合并的字段必须显式注册 reducer。
- reducer 必须确定性，并尽量满足结合性。
- 分支从同一快照开始，取消分支和失败尝试的结果不得合并。

示例：

```python
class State(BaseModel):
    findings: list[str] = Field(default_factory=list)
    reducers: ClassVar = {"findings": lambda current, new: current + new}
```

框架不自动猜测列表、字典或嵌套对象的深度合并方式。

#### 5. 失败和取消
阶段 3 采用 fail-fast：

- 一个分支失败后，不启动新的相关下游节点。
- 已启动的兄弟分支收到取消信号并完成清理。
- 根因节点记为 `FAILED`。
- 因失败传播而取消的已启动节点记为 `CANCELLED`。
- 未启动的依赖节点记为 `NOT_EXECUTED`。
- 每个节点只有一条最终 `StepRecord`。
- 不进行自动重试和超时处理。

调用方主动取消整个运行与分支失败传播是不同语义，阶段 4 会进一步统一调用方取消和超时策略。

#### 6. EventBus
EventBus 是旁路观察和通知机制，不参与 Graph 状态合并和核心控制流。事件至少包含：

```text
event_id、topic、run_id、source、created_at、payload
```

阶段 3 的限制：

- 仅进程内、内存存储
- at-most-once 投递
- 同一订阅者按发布顺序处理
- 不支持进程崩溃恢复、消费位点和持久化重试
- 支持同步/异步 handler、取消订阅和 close
- handler 异常默认记录并继续通知其他订阅者，可配置为使 publish 失败

#### 7. 报告和公共 API
`CompiledGraph.run()` 和 `GraphExecutor` 支持：

```python
max_concurrency: int | None = None
event_bus: EventBus | None = None
```

报告新增或使用以下信息：

- `StepRecord.wait_ms`
- `ExecutionReport.peak_concurrency`
- `ExecutionReport.event_stats`
- `FAILED`、`CANCELLED`、`NOT_EXECUTED` 的区分

这些字段必须提供兼容默认值，不能破坏阶段 1/2 报告的读取。

#### 8. 当前验收结果
- [x] fan-out 后所有分支执行一次
- [x] join 等待所有必需分支
- [x] `max_concurrency=1` 等价于串行行为
- [x] 并发限制不会超过配置值
- [x] 分支隔离和 reducer 冲突检测已测试
- [x] 失败传播取消、清理和终态区分已测试
- [x] EventBus 多订阅者、顺序、取消订阅和异常处理已测试
- [x] 阶段 1/2 原有测试继续通过
- [x] 当前共 74 个测试通过
- [ ] 报告字段变更完成提交并完成最终发布回归

#### 9. 进入阶段 4 的门禁
进入阶段 4 前必须：

- [ ] 提交阶段 3 的未提交代码变更
- [ ] 运行完整测试和包导入 smoke test
- [ ] 确认报告字段和 `../architecture/API.md` 一致
- [ ] 保留并记录并发基准结果
- [ ] 在 `ROADMAP.md` 中将阶段 3 标记为已完成

阶段 4 的详细方案见 [`PHASE4.md`](PHASES.md#phase-doc-phase4)。


<a id="phase-doc-phase4"></a>

## 原文：PHASE4.md

### 阶段 4：超时、重试、取消与错误策略（已完成）
#### 1. 当前基线
阶段 1～3 已建立以下能力：

- `BaseAgent`、类型化 State、`AgentResult` 和 `Runtime`
- `SequentialExecutor`
- 可校验的 Graph、条件路由和单路径执行
- fan-out/fan-in、显式 reducer 和有界并发
- `FAILED`、`CANCELLED`、`NOT_EXECUTED` 状态
- 进程内 EventBus
- 103 个离线测试通过

阶段 4 已完成阶段 3 发布收尾，确认 `StepRecord`/`ExecutionReport` 向后兼容，并将重试、超时、取消和尝试历史接入顺序/并发执行器。Checkpoint、进程恢复和持久化幂等属于下一阶段，详见 [`PHASE5.md`](PHASES.md#phase-doc-phase5)。

#### 2. 阶段目标
为 Agent 调用建立显式、可组合、可测试的可靠性策略：

1. 节点级超时
2. 可重试错误与不可重试错误分类
3. 最大尝试次数和指数退避
4. 调用方取消和取消传播
5. 失败、超时、取消和跳过的统一报告
6. 顺序 Graph、并发 Graph 和 SequentialExecutor 的一致行为

本阶段关注“单次运行如何可靠地完成或明确失败”，不实现 Checkpoint 和进程恢复。

#### 3. 关键语义区分
框架必须区分三种情况：

| 情况 | 含义 | 默认处理 |
|------|------|----------|
| Agent 业务失败 | Agent 正常启动，但返回 FAILED 或抛出业务错误 | 按错误分类决定重试或终止 |
| 节点超时 | Agent 在规定时间内没有完成 | 取消当前任务，按策略决定是否重试 |
| 调用方取消 | 用户、上层任务或进程主动取消整个运行 | 立即停止，不重试，向上传播取消 |

阶段 3 中“一个并行分支失败导致兄弟任务取消”属于失败传播；阶段 4 的调用方取消是整个运行的外部生命周期信号。两者必须在报告中可区分。

#### 4. 策略对象设计
建议使用不可变配置对象，而不是在 Executor 中散落多个布尔参数：

```python
RetryPolicy(
    max_attempts=3,
    backoff_base=0.5,
    backoff_max=30.0,
    jitter=0.1,
    retryable_exceptions=(TemporaryError,),
)

TimeoutPolicy(
    node_timeout=30.0,
)
```

建议再提供组合配置：

```python
ReliabilityPolicy(
    retry=RetryPolicy(...),
    timeout=TimeoutPolicy(...),
    on_failure="fail_fast",
)
```

要求：

- 参数在构造时校验
- `max_attempts >= 1`
- 超时和退避时间不能为负数
- 退避上限不能小于基础退避时间
- 策略对象尽量不可变
- 默认策略必须是 `max_attempts=1`、无超时、fail-fast，保持旧版本行为

#### 5. 重试设计
##### 5.1 尝试次数
`max_attempts` 表示总执行次数，而不是重试次数。例如 `max_attempts=3` 表示最多执行一次初始调用和两次重试。

每次尝试需要有稳定的上下文：

```text
run_id
node_id
attempt
started_at
finished_at
error
```

##### 5.2 默认不可重试的错误
以下错误默认不得重试：

- 状态字段未知或类型校验失败
- 并行状态合并冲突
- Graph 路由返回未知 label
- Graph 拓扑校验错误
- Agent 返回明确的不可重试错误
- `asyncio.CancelledError`

以下错误可由调用方显式配置为可重试：

- 临时网络错误
- 远程服务返回 429 或 5xx
- 临时数据库锁
- 明确标记为 transient 的业务错误

不能通过异常字符串模糊判断是否重试。应使用异常类型、错误码或 `RetryableError` 协议。

##### 5.3 退避算法
建议使用指数退避并设置上限：

```text
delay = min(backoff_max, backoff_base × 2^(attempt - 1)) + jitter
```

生产实现必须避免所有任务在同一时刻同步重试。测试中应注入 sleeper 和随机数生成器，不使用真实长时间 `sleep`。

##### 5.4 状态副作用
重试前必须明确 Agent 是否有外部副作用。阶段 4 要求：

- 状态只在一次尝试成功并返回有效结果后合并
- 失败尝试的部分结果不得合并
- 有副作用的 Agent 必须由调用方声明幂等性或使用幂等键
- EventBus 生命周期事件可以记录每次尝试，但不能将失败尝试当作成功结果

#### 6. 超时设计
##### 6.1 节点级超时
使用 `asyncio.wait_for()` 或 Python 3.11 的等价机制包裹单个 Agent 调用。超时后：

- 当前任务收到取消
- 等待清理完成
- 记录 `TimeoutError` 和实际尝试次数
- 未完成的 AgentResult 不参与状态合并
- 根据 RetryPolicy 决定是否再次尝试

##### 6.2 超时范围
阶段 4 首版只实现节点级超时。全局运行超时需要与并发调度、Checkpoint 和恢复结合，暂不作为默认功能。

##### 6.3 清理保证
Agent 可能在 `finally` 中释放资源。Executor 必须等待取消后的清理完成，不能留下后台任务。测试需要使用 Event/barrier 验证清理已发生，而不是仅等待固定时间。

#### 7. 取消设计
##### 7.1 调用方取消
当外层任务取消 `graph.run()` 时：

- 取消信号传播到当前 Agent 和全部并发子任务
- 不进行重试
- 不合并未完成结果
- EventBus 可以发布运行取消事件，但发布失败不能阻止取消清理
- `CancelledError` 应按 asyncio 约定向上传播，或转换为明确的顶层运行状态，但不能静默吞掉

##### 7.2 失败传播取消
保留阶段 3 行为：一个分支失败时取消同一 fan-out 中的兄弟任务。报告区分：

- 失败根因节点：`FAILED`
- 因根因被取消的已启动节点：`CANCELLED`
- 因依赖失败而未启动的节点：`NOT_EXECUTED`

每个节点仍只能产生一条最终 `StepRecord`，尝试历史放在该记录的 `attempts` 或独立报告字段中。

#### 8. 错误策略
首版支持以下策略：

```text
fail_fast       当前节点最终失败后停止运行
skip_dependents 当前节点失败，跳过依赖它的节点
continue        记录失败并继续无依赖节点（仅在图语义允许时）
```

建议阶段 4 默认只开放 `fail_fast`，其他策略先完成类型设计和测试后再开放。并行图不能简单套用顺序图的 `continue`，因为需要重新定义 join 的就绪条件和部分结果语义。

错误对象至少包含：

- 错误类型
- 错误码或是否可重试
- Agent / node ID
- `run_id`
- 当前尝试次数
- 最终错误信息
- 是否由超时或取消触发

错误信息不得包含 API Key、完整敏感输入或不必要的外部响应正文。

#### 9. 报告设计
不破坏已有 `ExecutionReport` 和 `StepRecord` 字段。推荐增加可选字段：

```text
StepRecord:
  attempts: list[AttemptRecord]
  terminal_reason: success | failed | timeout | cancelled | skipped

AttemptRecord:
  attempt
  started_at
  finished_at
  duration_ms
  status
  error

ExecutionReport:
  cancellation_reason
  retry_count
  timeout_count
```

如果暂不新增模型，至少要保证 `metadata` 结构稳定、可序列化，并在 API 文档中定义字段。报告要能回答：

- 总共尝试了几次？
- 哪一次超时或失败？
- 最终失败的原因是什么？
- 哪些节点是因为取消而结束？
- 哪些状态更新真正被合并？

#### 10. 推荐实现结构
```text
src/magent/
├── reliability/
│   ├── policy.py       # RetryPolicy、TimeoutPolicy、ReliabilityPolicy
│   ├── errors.py       # RetryableError、NonRetryableError、TimeoutError
│   └── runner.py       # 单节点调用、超时、重试、清理
├── core/
│   ├── result.py       # 兼容终态和尝试状态
│   └── executor.py     # SequentialExecutor 接入策略
└── graph/
    └── executor.py     # 顺序/并发 Graph 接入统一 runner
tests/unit/
├── test_retry_policy.py
├── test_timeout.py
├── test_cancellation.py
├── test_error_strategy.py
└── test_attempt_report.py
```

推荐将“调用单个 Agent 的可靠性 runner”抽出来，由顺序 Executor 和 Graph Executor 共同使用，避免两套重试和超时逻辑逐渐产生差异。

#### 11. 任务拆分
##### Task 0：阶段 3 发布收尾
提交 `core/executor.py` 的报告字段变更；确认 74 个测试、公共导出和文档一致；建立阶段 4 的干净基线。

##### Task 1：策略和错误类型
实现策略对象、参数校验、可重试错误协议和默认策略。默认行为必须与现有版本一致。

##### Task 2：统一单节点 Runner
实现一次 Agent 调用的超时、异常分类、重试和状态结果返回；注入 clock、sleeper 和 jitter 生成器。

##### Task 3：接入 SequentialExecutor
保持阶段 1 的顺序和 fail-fast 语义，增加配置化重试和节点超时；补充报告中的尝试历史。

##### Task 4：接入顺序 Graph
让条件路由节点和普通节点使用同一可靠性 Runner，确保路由失败、状态更新失败不会被错误重试。

##### Task 5：接入并发 Graph
处理并发分支的节点超时、兄弟取消、调用方取消和任务清理；确保失败尝试与取消尝试不参与 reducer。

##### Task 6：报告、EventBus 和文档
发布尝试开始、尝试失败、超时、重试和最终状态事件；更新 `../architecture/API.md`、README 和 `COMPARISON.md`。

##### Task 7：基准与提交
比较无重试、重试成功、超时失败和并发取消场景的耗时与资源；形成阶段 4 独立提交。

#### 12. 测试要求
##### 策略和重试
- [x] `max_attempts=1` 不发生重试
- [x] 可重试错误按最大次数执行
- [x] 不可重试错误立即终止
- [x] 退避时间遵守上限
- [x] jitter 可注入且测试可重复
- [x] 重试成功后只合并最后一次成功结果
- [x] 所有失败尝试都出现在尝试历史中

##### 超时和取消
- [x] 节点超时后任务被取消并完成清理
- [x] 超时不合并未完成结果
- [x] 超时可按策略重试
- [x] 调用方取消不会触发重试
- [x] 调用方取消会传播到所有并发子任务
- [x] 失败传播取消与调用方取消可区分
- [x] 不存在遗留后台任务

##### 错误和兼容性
- [x] 状态校验错误不重试
- [x] reducer 冲突不重试
- [x] 路由未知 label 不重试
- [x] `FAILED`、`TIMEOUT`、`CANCELLED`、`NOT_EXECUTED` 可区分
- [x] 每个节点只有一条最终步骤记录
- [x] 阶段 1～3 的原有测试全部通过
- [x] 无策略配置时旧行为不变

##### 质量验收
- [x] 阶段 4 新增不少于 20 个有意义的离线测试
- [x] 不使用真实长时间 sleep，使用注入的 sleeper 或同步控制器
- [x] 测试不访问网络、真实数据库或 LLM
- [x] 报告可以 JSON 序列化和反序列化
- [x] 运行日志不泄露敏感信息

#### 13. 完成定义
```text
阶段 3 发布收尾
        ↓
策略对象和错误分类稳定
        ↓
单节点超时/重试 Runner 可测试
        ↓
SequentialExecutor 和 Graph Executor 共用语义
        ↓
并发取消和资源清理无泄漏
        ↓
报告能解释每次尝试和最终结果
        ↓
旧行为兼容、测试和基准完成
```

完成阶段 4 后，才进入阶段 5 的 Checkpoint、恢复和幂等设计。Checkpoint 应复用本阶段已经稳定的运行 ID、节点 ID、尝试记录和状态边界。

#### 14. 建议提交
```text
chore(phase3): close release gate
feat(reliability): add retry and timeout policies
feat(reliability): add unified node runner
feat(core): integrate reliability with sequential executor
feat(graph): integrate reliability with graph executors
test(reliability): cover timeout retry and cancellation
docs: document phase-4 reliability semantics
```


<a id="phase-doc-phase5"></a>

## 原文：PHASE5.md

### 阶段 5：Checkpoint、恢复与幂等（已完成）
#### 1. 当前基线
阶段 1～5 的功能实现已完成，阶段 5 发布门禁已关闭并形成提交；当前全量回归为 `168 passed`。
阶段 5 在 `f45c672`（阶段 4 末）之后实现，已将“一次运行的内存状态”变成“可验证、可恢复的
本地执行记录”。现有实现已经提供：

- `BaseAgent`、类型化 State、`AgentResult`、`Runtime`
- `SequentialExecutor` 和已校验的 DAG `GraphExecutor`
- 条件路由、fan-out/fan-in、显式 reducer 和有界并发
- `EventBus`
- 节点超时、显式可重试错误、指数退避、调用方取消和失败传播
- `run_id`、`StepRecord`、`AttemptRecord` 以及成功后才合并状态的边界
- `CheckpointStore` 抽象、`InMemoryCheckpointStore`、`SqliteCheckpointStore`
- `SequentialExecutor.resume` / `GraphExecutor.resume` 以及 `SideEffectSink` / `execution_key`

阶段 5 的首要任务已经完成，下一步进入阶段 7 VulnTell 纵向示例，而不是继续扩展框架核心；
`checkpoint_store=None` 时执行器行为与阶段 1～4 完全一致。

阶段 5 发布门禁已针对以下风险完成验证；这些边界仍作为后续业务接入时的长期约束：

- 从 SQLite 读取 checkpoint 时重新校验 checksum，而不只信任数据库中的 checksum 字段；
- 并发 Graph 写入 checkpoint 时使用统一的进程内序列分配机制；
- `SideEffectSink` 对同一 execution key 使用原子 claim/处理中状态；
- 非字典副作用结果的首次返回值与重放返回值保持同一结构；
- `RunRecord.status`、失败/取消/中断边界和 `NODE_STARTED` 的真实 attempt 信息与报告和恢复逻辑一致；
- 失败、损坏、取消和存储异常路径关闭资源，并明确已持久化状态。

#### 2. 阶段目标
完成后，框架应能够：

1. 在节点执行前、节点成功提交后保存可序列化的状态快照；
2. 使用稳定的 `run_id`、图/节点版本和单调递增的 checkpoint 序号识别一次运行；
3. 进程中断后从最近一次成功提交的边界恢复，不重复执行已提交节点；
4. 对恢复时尚处于 `RUNNING` 的节点按“执行结果未知”处理，并使用稳定幂等键重试；
5. 将阶段 4 的重试、超时、取消和尝试记录持久化到同一运行历史中；
6. 对重复提交、重复恢复、快照损坏、缺失和版本不兼容给出确定性结果；
7. 在顺序 DAG 和并发 fan-out/fan-in DAG 中保持相同的“成功提交才推进 frontier”语义。

本阶段的可靠性目标是：框架管理的状态提交具有原子性，外部副作用在使用幂等协议时具有
可安全重试性。不能把任意外部 API 或数据库调用承诺为绝对 exactly-once。

#### 3. 范围与非目标
##### 3.1 本阶段包含
- `CheckpointStore` 抽象和 SQLite 本地实现；
- 运行元数据、状态快照、节点边界、尝试历史和恢复游标；
- `SequentialExecutor` 与 `GraphExecutor` 的 checkpoint 接入；
- 显式 `resume` API，默认不自动恢复；
- 稳定的节点版本、工作流/图版本和状态 schema 指纹；
- 执行键（idempotency key）生成协议及框架内的幂等记录；
- 破坏恢复条件时的结构化错误和诊断信息；
- 至少 20 个离线单元/集成测试和一个可重复的中断恢复示例。

##### 3.2 本阶段不包含
- 多进程、多机或分布式 checkpoint 协议；
- 主从切换、租约、领导者选举和消息队列；
- 跨数据库、外部 API 与 checkpoint 的分布式事务；
- 任意 Python 对象的 pickle 持久化；
- 自动迁移旧状态 schema；
- 循环图、动态规划、LLM、工具注册或 VulnTell 业务实现；
- 加密密钥管理和云端对象存储适配器。

##### 3.3 阶段风险与注意事项
- Checkpoint 写入与进程崩溃之间始终存在窗口；“外部副作用已发生、成功记录尚未提交”必须按未知结果设计，不能靠状态快照猜测。
- 取消信号可能到达状态合并或 SQLite 提交附近。提交必须有清晰的原子边界，并通过故障注入测试验证不会出现“报告成功但没有持久化状态”。
- Agent、router 和 reducer 的非确定性会破坏恢复一致性。已选择的路由必须持久化；影响状态的 reducer 必须保持确定性，不能依赖完成顺序、当前时间或随机数。
- 节点 ID、节点 version 和 workflow version 不是展示字段，而是恢复安全条件。行为、提示词、工具协议或输出 schema 改变时必须升级版本。
- 全量 JSON 快照简单可靠但可能放大磁盘和写入开销。阶段 5 先保证语义，压缩、增量快照和归档留到后续，不得为优化跳过成功边界。
- SQLite 是单机单写者存储。需要设置明确的锁/忙等待和事务超时；不能通过无限重试掩盖数据库损坏或资源泄漏。
- 状态可能包含凭据、漏洞原文或个人数据。默认不写入密钥和敏感日志；阶段 5 不提供加密时，应在文档中要求安全文件权限和调用方脱敏。
- 恢复调度必须防止重复创建同一个逻辑节点的任务。frontier、已提交集合和 execution key 要共同参与去重，不能只依赖内存 `tasks`。

#### 4. 必须先冻结的恢复语义
##### 4.1 Checkpoint 是提交记录，不是日志缓存
每次 checkpoint 都必须是完整、可独立校验的记录，至少包含：

```text
schema_version
run_id
workflow_id / workflow_version
node_id / node_version（运行级 checkpoint 可为空）
checkpoint_seq
phase
attempt
state_type / state_schema_hash
input_state（节点开始记录）
output_state 或 merged_state（成功提交记录）
updates
route / activated_nodes（条件路由或并发激活信息）
frontier（下一批可执行节点及其依赖状态）
attempt_records
created_at
checksum
```

SQLite 中使用事务写入，`checkpoint_seq` 在同一 `run_id` 内单调递增。读取最新记录时必须按
序号和 checksum 校验，不能只按文件修改时间判断“最新”。

##### 4.2 节点状态边界
推荐的生命周期为：

```text
RUN_STARTED
    ↓
NODE_STARTED（保存输入快照和幂等键）
    ↓
NODE_ATTEMPT_*（记录阶段 4 尝试历史）
    ↓
NODE_COMMITTED（保存合并后的状态和 frontier）
    ↓
RUN_COMPLETED / RUN_FAILED / RUN_CANCELLED
```

只有 `NODE_COMMITTED` 才能把节点加入已完成集合并推进 frontier。失败、超时、调用方取消和
`NOT_EXECUTED` 都不能提交其未完成的 `updates`。节点成功返回后，必须先验证并合并状态，再
以一个原子提交记录写入“结果 + 新 frontier”；不能先把节点标记成功、再异步写状态。

进程在 `NODE_STARTED` 之后中断时，节点结果属于未知状态。恢复默认从该节点的输入快照重新
执行，而不是假定成功；这会形成 at-least-once 执行，因此必须使用相同的幂等键。

##### 4.3 顺序 Graph 恢复
顺序执行器保存：初始状态、已提交节点顺序、最后成功状态和下一个节点索引。恢复时：

- 已有成功提交的节点不得再次调用 Agent；
- 最近一个未提交或 `RUNNING` 节点从其 `input_state` 重新调用；
- `RUNNING` 记录对应的未完成尝试应标记为 `ABANDONED`（只在 checkpoint 历史中使用）；
- 阶段 4 的 `max_attempts` 默认包含已经持久化的尝试和恢复后新增的尝试；
- 已提交状态与调用方传入的初始状态不一致时拒绝恢复，不静默覆盖。

##### 4.4 并发 Graph 恢复
并发 Graph 不能只保存一个“当前状态”。必须保存每个已激活节点的输入快照、节点提交结果、
分支更新、条件路由结果、join 所需父节点集合以及 frontier。

- 同一 fan-out 的各分支从并行源的已提交快照恢复；
- 已成功提交的分支不重跑，其 updates 仍可供 join 使用；
- 未提交的分支独立恢复，不得读取兄弟分支的中间状态；
- join 只有在所有要求的父节点都成功提交后才能提交；
- join 提交前进程中断时，恢复应依据父节点提交记录重新计算合并，并继续执行 join；
- reducer 仍按声明的父节点顺序执行，不能按 checkpoint 到达顺序产生不同结果；
- 已选择的条件路由必须从 checkpoint 恢复，不得因路由函数再次执行而改变路径。

恢复后的调度不要求复现原来的完成时间或任务交错顺序，但必须复现已提交状态、路由和 reducer
结果。无法重建这些信息时应失败并报告原因，而不是猜测。

#### 5. 存储抽象与 SQLite 方案
##### 5.1 `CheckpointStore` 最小契约
建议先定义稳定的领域模型，再实现 SQLite，不让 Executor 直接拼接 SQL：

```python
class CheckpointStore(Protocol):
    async def create_run(self, run: RunRecord) -> None: ...
    async def append(self, checkpoint: CheckpointRecord) -> None: ...
    async def latest(self, run_id: str) -> CheckpointRecord | None: ...
    async def load_run(self, run_id: str) -> RunRecord: ...
    async def record_effect(self, record: EffectRecord) -> bool: ...
    async def get_effect(self, execution_key: str) -> EffectRecord | None: ...
    async def close(self) -> None: ...
```

实际命名可以调整，但必须满足：追加记录不可静默覆盖、相同 `run_id + checkpoint_seq` 重复提交
具有幂等结果、不同内容的冲突会显式报错、读写失败不会返回伪造的成功状态。接口应为异步，
SQLite 适配器不得在 Agent 执行期间长时间阻塞事件循环。

##### 5.2 建议的 SQLite 表
```text
runs
  run_id PK, workflow_id, workflow_version, state_type, state_schema_hash,
  initial_state_json, status, created_at, updated_at

checkpoints
  run_id, checkpoint_seq, phase, node_id, node_version, attempt,
  input_state_json, output_state_json, updates_json, frontier_json,
  route_json, attempts_json, checksum, created_at,
  UNIQUE(run_id, checkpoint_seq)

effects
  execution_key PK, run_id, node_id, node_version, status, result_json,
  created_at
```

SQLite 实现至少启用参数化 SQL、事务、外键（如适用）、WAL/忙等待策略和明确的连接关闭流程。
`checkpoints` 保存 JSON 文本；写入前必须通过 State schema 校验，读取后必须再次校验。禁止
使用 pickle 绕过 schema 和安全边界。

#### 6. 版本、校验和恢复兼容性
恢复前至少比较以下信息：

- `run_id` 是否存在且状态允许恢复；
- workflow/graph ID 与显式 version；
- 节点 ID 和节点 version；
- State 类型标识与 `model_json_schema()` 的稳定 hash；
- checkpoint 格式 `schema_version`；
- 每条记录 checksum 和序号连续性（允许明确记录的压缩/归档策略除外）。

不兼容时抛出专用 `CheckpointCompatibilityError`，错误中指出字段、期望值和实际值。阶段 5
不做隐式迁移；未来若需要迁移，应使用显式 migration version 和离线迁移工具。

节点 version 必须是业务方可控制的稳定字符串。代码或提示词、工具协议、输出 schema 会影响
结果时必须升级 version。框架可以提供默认 version 以兼容旧 Agent，但 checkpoint-enabled
运行的文档和测试必须覆盖显式 version；不能声称自动检测任意函数体变化。

#### 7. 幂等设计与已知边界
##### 7.1 执行键
同一个逻辑节点执行的重试和恢复必须复用同一个逻辑执行键，建议由以下内容规范化后生成：

```text
execution_key = hash(
    run_id,
    node_id,
    node_version,
    canonical(input_state),
    logical_operation_name,
)
```

`attempt` 不得放入执行键，否则重试会被错误地视为新副作用。键生成必须稳定、可审计并避免
把密钥或完整敏感输入写入日志。若同一键再次请求，幂等层应返回已记录结果，或明确返回
“处理中/结果未知”，不能重复执行未受保护的写入。

##### 7.2 能保证什么
- 框架内的状态 checkpoint 提交：在 SQLite 事务成功后视为一次提交，重复提交同一记录不会
  产生第二份逻辑结果；
- 通过 `effects` 或业务数据库唯一键保护的写入：相同执行键可安全重试；
- 不受框架控制的外部 API、消息发送和文件写入：最多只能保证 at-least-once，不能由
  checkpoint 单独推出 exactly-once。

因此下游 Agent 必须将“调用外部副作用”和“返回状态更新”分开设计，并声明副作用是否可重试。
阶段 5 的测试应使用一个可控的 fake side-effect sink，模拟“副作用已发生但进程在 checkpoint
前崩溃”的窗口，验证相同 execution key 不重复写入。

#### 8. 与阶段 4 的衔接
- `run_id` 沿用现有执行报告中的值，恢复不能生成新的 run ID；
- `AttemptRecord` 增加持久化边界所需的序列/状态信息时保持旧字段兼容；
- 超时、重试和取消仍由 `run_node` 统一处理，Checkpoint 不复制一套重试逻辑；
- 退避等待期间进程中断时，恢复应依据已记录的尝试次数决定是否还允许重试；
- 调用方取消只提交 `RUN_CANCELLED` 和已完成节点，不能把取消中的节点标为成功；
- 失败传播取消的兄弟分支保持 `CANCELLED`/`NOT_EXECUTED` 区分，只有成功提交的分支进入 join；
- EventBus 仍是旁路通知。事件丢失不能改变 checkpoint，也不能把事件当作恢复依据。

#### 9. 推荐任务拆分
##### Task 0：冻结协议和基线
整理 `RunRecord`、`CheckpointRecord`、`EffectRecord`、checkpoint phase 和兼容性错误的字段；
确认现有 103 个测试全部通过，补充一份状态快照 JSON fixture。不得在此任务中接入 SQLite。

##### Task 1：Checkpoint 领域模型与抽象
实现不可变/只读的记录模型、序列化/反序列化、canonical JSON、checksum 和
`CheckpointStore` 契约。覆盖缺字段、未知 phase、非法序号和校验失败。

##### Task 2：SQLite Store
实现数据库初始化、事务追加、最新记录读取、重复提交、并发读写、关闭和损坏处理。所有 SQL
使用参数绑定；测试使用 `tmp_path`，不依赖固定本地路径。

##### Task 3：顺序执行器接入
增加 checkpoint 配置和显式 `resume` 入口；在节点前写入输入快照，在成功合并后原子提交结果与
frontier。验证进程中断后不重新调用已提交节点。

##### Task 4：统一恢复控制器
抽取恢复游标、版本检查、`RUNNING → ABANDONED` 处理和报告重建逻辑。恢复应复用现有
`run_node`，不能在 Executor 中复制重试/超时实现。

##### Task 5：并发 Graph 接入
持久化分支输入、分支 updates、路由激活信息和 join 父节点提交集合；验证 reducer 顺序、
分支隔离和部分分支恢复。先支持已有无环 DAG，不为恢复引入循环或动态节点。

##### Task 6：幂等记录与副作用测试夹具
实现 execution key、effect record 和一个 fake sink 适配器；明确“已记录结果”“处理中”“结果
未知”三种状态的处理。不得把任意真实外部服务接入测试。

##### Task 7：报告、文档与示例
让 `ExecutionReport` 能说明是否恢复、恢复自哪个 checkpoint、跳过了哪些已提交节点、发生了
多少 abandoned/replayed attempts；更新 `../architecture/API.md`、`../architecture/DESIGN.md` 和 README，并提供
离线中断恢复示例。

##### Task 8：回归与阶段发布
运行全量离线测试、序列化兼容测试和资源清理检查；记录 SQLite 版本、Python 版本和测试数量，
形成阶段 5 独立提交。

#### 10. 测试要求
至少新增 20 个有意义的离线测试，建议覆盖：

##### Store 与数据完整性
- [ ] 新建 run、追加 checkpoint、读取最新 checkpoint；
- [ ] 相同序号和相同内容重复提交不重复产生逻辑记录；
- [ ] 相同序号但内容不同显式报冲突；
- [ ] checksum 错误、JSON 损坏、序号倒退和缺失 run 被拒绝；
- [ ] 状态 schema 不匹配、checkpoint version 不兼容被拒绝；
- [ ] SQLite 事务失败后没有半条成功 checkpoint；
- [ ] 多个 store 操作关闭后不会泄漏连接或后台任务。

##### 顺序恢复
- [ ] 第一个节点成功提交后中断，恢复时只执行后续节点；
- [ ] 节点执行中断，恢复从该节点 input snapshot 重跑；
- [ ] 已提交节点不会因重复调用 `resume` 再执行；
- [ ] 恢复保持原 `run_id`，并合并正确的最终 state；
- [ ] 恢复后 attempt 编号连续，abandoned attempt 可追溯；
- [ ] 恢复与阶段 4 重试、超时、取消组合时不重复合并失败结果。

##### 并发恢复与幂等
- [ ] 一个分支成功、另一个分支中断时，只恢复未提交分支；
- [ ] join 等待全部成功父节点，不能消费取消或未执行分支；
- [ ] reducer 使用声明顺序，和原始完整运行结果一致；
- [ ] 条件路由结果从 checkpoint 恢复，不再次调用 router；
- [ ] 副作用已发生但提交前中断时，相同 execution key 不重复写入；
- [ ] 不同 run、node、version 或 input 的 key 不发生错误碰撞；
- [ ] 重复 resume、重复完成提交和重复 effect 请求结果稳定。

##### 兼容与质量门禁
- [ ] 阶段 1～4 全部原有测试继续通过；
- [ ] 无 `checkpoint_store` 时行为和性能不改变；
- [ ] 所有状态仅经过 Pydantic schema 校验，禁止 pickle；
- [ ] checkpoint 和 report 可 JSON 序列化/反序列化；
- [ ] 测试不访问网络、真实 LLM 或真实外部副作用系统；
- [ ] 运行结束、异常和取消路径均关闭 SQLite 资源。

#### 11. 量化验收标准（功能实现）
阶段 5 只有同时满足以下条件才算完成：

1. 全量测试通过，阶段 5 新增测试不少于 20 个；
2. 至少提供顺序 DAG 和 fan-out/fan-in DAG 各一个中断恢复集成测试；
3. 已成功提交的节点恢复时调用次数保持为 0，未提交节点最多按策略重新执行；
4. 恢复后的 `run_id`、状态、路由、join/reducer 结果与无中断基线一致；
5. 模拟“外部写入已完成、checkpoint 尚未提交”的故障窗口，重复执行键的写入次数为 1；
6. 损坏、缺失、版本不兼容和重复提交均有专用错误或明确结果，不能静默降级；
7. `checkpoint_store=None` 时阶段 1～4 测试全部通过，且不产生本地数据库文件；
8. README、`DESIGN.md`、`API.md`、`ROADMAP.md` 和本文件对当前实现状态一致；
9. 不宣称任意外部副作用 exactly-once，文档明确 at-least-once 与幂等适配边界；
10. 形成至少一个独立的阶段 5 实现提交和一个文档/验收提交。

#### 12. 当前发布门禁（已关闭）
阶段 5 的核心功能和测试已经完成，发布门禁已关闭。进入阶段 7 前已完成
以下收尾动作：

- [x] 为 SQLite 读取路径增加 checksum 重算和校验测试；
- [x] 为并发 Graph 增加 checkpoint 序号分配、重复序号和恢复测试；
- [x] 为 `SideEffectSink` 增加同一 execution key 的并发 claim/处理中测试；
- [x] 统一副作用首次返回与重放返回的结果结构；
- [x] 更新并持久化 `RunRecord.status`，覆盖 completed/failed/cancelled/abandoned；
- [x] 验证所有 checkpoint store、SQLite 连接和取消/异常路径的资源关闭；
- [x] 更新 README、API、ROADMAP 和本文件的状态描述；
- [x] 在干净环境运行全量测试、类型检查、离线示例和 `import magent`；
- [x] 形成阶段 5 实现提交和发布文档提交，并记录测试数量与环境。

阶段 5 状态为“已完成”，阶段 6 工具副作用和阶段 7 业务接入可以使用其幂等与恢复能力。

#### 13. 完成定义
```text
冻结快照/版本/幂等协议
        ↓
CheckpointStore 抽象和 SQLite 事务实现
        ↓
顺序执行器成功边界持久化
        ↓
中断后恢复与版本拒绝
        ↓
并发分支、join、路由恢复
        ↓
副作用 execution key 和重复写入保护
        ↓
报告、示例、测试和资源清理完成
```

阶段 5 完成后，框架才具备支撑 VulnTell 长流程采集和 SQLite 幂等持久化的基础。LLM、工具和
VulnTell 业务实现仍应放在后续阶段，不能为了通过恢复测试而把业务模型塞进 `magent` 核心。

#### 14. 建议提交节奏
```text
design(phase5): freeze checkpoint and idempotency semantics
feat(checkpoint): add records serialization and store protocol
feat(checkpoint): add sqlite checkpoint store
feat(checkpoint): persist sequential execution boundaries
feat(checkpoint): add resume and compatibility checks
feat(checkpoint): recover concurrent graph frontier
feat(checkpoint): add idempotency records and fake sink
test(checkpoint): cover interruption recovery and duplicate effects
docs: document phase-5 checkpoint semantics
```


<a id="phase-doc-phase6"></a>

## 原文：PHASE6.md

### 阶段 6：工具协议、LLM Agent 与 Middleware 实施计划
> **实施状态：已完成。** 工具协议、`LLMProvider`/`FakeProvider`/可选 OpenAI 适配器、
> 以及可组合 Middleware 均已实现并通过测试（阶段 6 新增 38 个测试，全量 168 个离线测试通过，
> `mypy src/magent` 无错误）。阶段 5 发布门禁已全部关闭，阶段 6 代码、文档、示例与公共导出已提交。
> 核心在无 API Key/网络/LLM 服务时仍可运行。

#### 1. 阶段定位
阶段 1～4 已建立 Agent、类型化 State、DAG 编排、并发、EventBus 和可靠性策略；阶段 5
已经实现本地 Checkpoint、恢复和幂等能力并完成发布门禁。阶段 6 在此基础上增加
“Agent 如何安全调用工具”和“如何可选接入 LLM”的扩展层，同时用 Middleware 统一实现
日志、限流、策略检查和运行前后钩子。

本阶段的目标不是把 `magent` 变成某一家模型厂商的 SDK，而是冻结最小、可替换、可测试的
扩展协议，为后续 VulnTell 数据源采集和报告生成提供基础。所有 LLM 能力必须是可选依赖；
没有 API Key、网络和 LLM 服务时，框架核心及确定性 Agent 仍必须可运行。

#### 2. 当前基线审视
##### 已完成
- 类型化 `BaseAgent` / `AgentResult` / `Runtime`；
- 顺序 Executor 和支持条件路由、fan-out/fan-in 的 DAG Executor；
- 显式重试、节点超时、调用方取消和失败传播；
- EventBus 旁路事件机制；
- `CheckpointStore`、SQLite 快照、顺序/并发 DAG 恢复和 `SideEffectSink`；
- 阶段 5 测试通过，当前全量测试为 168 个（含阶段 6 新增 38 个工具/LLM/Middleware 测试）。

##### 阶段 5 必须先完成的发布门禁（已关闭）
阶段 6 的功能开发不得以“顺便修复”为名绕过以下问题（均已关闭并附测试）：

1. SQLite 读取 checkpoint 后重新计算并校验 checksum（`sqlite.py` 在 `_fill_workflow` 之后 `_verify_checksum`）；
2. 并发 Graph 的 checkpoint 序号由统一机制分配，不能出现重复序号（`graph/executor.py` 用 `seq[0]` + `asyncio.Lock`）；
3. `SideEffectSink` 对同一 execution key 的并发请求具备原子 claim/处理中语义（每键 `asyncio.Lock`）；
4. 副作用结果首次返回与重放返回的数据结构一致（统一存储/返回 `result_json`）；
5. `RunRecord.status` 与成功、失败、取消和中断状态保持一致（`update_run_status` 在首尾写 checkpoint）；
6. 恢复时的 abandoned attempt、节点版本和 frontier 可追溯且有测试覆盖（`tests/unit/test_phase5_checkpoint.py`）；
7. 阶段 1～5 的代码、文档、示例和公共导出形成一个独立提交（阶段 5 提交节奏见 `ROADMAP.md`）。

门禁关闭后，阶段 6 工具副作用已可安全接入恢复流程（通过 `SideEffectSink` 幂等）。

#### 3. 阶段目标
完成后，框架应提供：

1. 统一的 Tool 描述、注册、输入校验、执行和输出校验协议；
2. 同步工具与异步工具的统一调用方式，并避免同步阻塞事件循环；
3. 工具超时、取消、错误分类、白名单和基础限流能力；
4. 可替换的 `LLMProvider` 接口、确定性 Fake Provider 和至少一个可选适配器；
5. LLM 请求/响应的结构化模型、token/耗时元数据和敏感信息脱敏；
6. Agent/Tool Middleware 的确定性组合、执行顺序和异常传播语义；
7. 工具调用与阶段 4、阶段 5 的重试、Checkpoint 和幂等边界衔接清楚；
8. VulnTell 可以在后续阶段通过插件使用这些协议，而不修改 `magent` 核心执行逻辑。

#### 4. 范围与非目标
##### 4.1 本阶段包含
- `magent.tools`：ToolSpec、ToolRegistry、ToolContext、ToolResult、ToolError；
- 输入/输出 schema 校验和可序列化工具结果；
- 同步函数、异步函数和受控线程池适配；
- 工具级 timeout、取消传播、限流和白名单；
- `magent.llm`：消息、请求、响应、Provider 协议和 Fake Provider；
- 一个单独的可选 Provider adapter，依赖和导入不能污染核心包；
- `magent.middleware`：Agent/Tool middleware protocol、组合器和最小内置中间件；
- EventBus 事件和 ExecutionReport 的工具/LLM 调用摘要；
- 离线 fixture、契约测试、示例和 API 文档。

##### 4.2 本阶段不包含
- 自动规划、循环 Agent、自主修改 Graph 或多 Agent 社交协议；
- 绑定 OpenAI、Anthropic 或其他厂商的核心数据模型；
- 在测试中访问真实模型、网络、漏洞源或生产数据库；
- 自动执行命令行、任意 Python 代码、任意 URL 抓取或漏洞利用；
- 把 LLM 输出直接当作可信状态更新或评分结果；
- 分布式 Tool Registry、远程沙箱、密钥管理平台和多租户隔离；
- 在本阶段实现 VulnTell 业务 Agent。

#### 5. 核心协议设计
##### 5.1 Tool 协议
建议提供如下最小领域模型，具体字段可在 Task 0 冻结：

```python
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    side_effect: bool = False
    idempotent: bool = False

class Tool(Protocol):
    spec: ToolSpec
    async def invoke(self, arguments: BaseModel, context: ToolContext) -> ToolResult: ...

class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str, version: str | None = None) -> Tool: ...
    async def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolResult: ...
```

约束：

- 工具名和版本在注册时校验，重复注册不能静默覆盖；
- 原始字典先通过 `input_model` 校验，再传给工具；工具返回值必须通过 `output_model` 校验；
- `ToolResult` 只允许结构化数据、状态和脱敏元数据，不把任意异常正文直接放入 State；
- 同步函数通过 `asyncio.to_thread` 或受控 executor 执行，不能在事件循环中直接阻塞；
- 线程任务收到取消时，要记录“调用已取消但底层同步函数可能仍在运行”的事实，不能虚假宣称已终止；
- 工具本身不直接修改框架 State，必须返回结果，由 Agent 决定如何形成 `AgentResult`；
- 工具 schema、版本和副作用属性应进入 checkpoint/trace 元数据，便于恢复兼容检查。

##### 5.2 ToolContext 与安全策略
`ToolContext` 只暴露必要的 `run_id`、`node_id`、工具版本、取消信号、日志器、Checkpoint
存储和幂等能力。不得把任意 executor 内部对象或数据库连接暴露给工具。

Registry 或 Middleware 至少提供：

- 显式工具 allowlist，默认拒绝未登记工具；
- 每个工具的最大输入/输出大小；
- 每次调用的 timeout 和并发/速率限制；
- 参数和结果日志脱敏；
- `side_effect=True` 时要求显式声明幂等策略；
- 禁止 shell、动态导入和任意代码执行工具进入默认示例。

对于 URL、文件和命令类工具，本阶段只定义策略接口和拒绝默认值，不为了演示而放开 SSRF、
任意路径或任意命令执行。

##### 5.3 LLM Provider 协议
核心只依赖抽象消息和结构化响应：

```python
class LLMProvider(Protocol):
    name: str
    version: str
    async def complete(self, request: LLMRequest, context: LLMContext) -> LLMResponse: ...

class LLMRequest:
    messages: list[ChatMessage]
    model: str
    temperature: float = 0.0
    tools: list[ToolSpec] = []
    response_schema: type[BaseModel] | None = None

class LLMResponse:
    message: ChatMessage
    finish_reason: str
    usage: Usage | None
    raw_metadata: dict
```

要求：

- Provider 只返回结构化 `LLMResponse`，不能让厂商 SDK 类型穿透 `magent` 核心；
- Provider 异常映射为统一错误码，并区分限流、临时故障、认证失败、参数错误和内容拒绝；
- `response_schema` 存在时，模型输出必须经过校验，失败不得直接写入 State；
- 默认温度和 Fake Provider 结果必须确定性，便于离线重放；
- 记录 provider/model/version，但不记录 API Key、完整 Authorization header 或未脱敏 prompt；
- LLM 输出中的工具名和参数必须再次经过 Registry allowlist 与 schema 校验；
- 外部文本只能视为不可信输入，不能让其改变系统工具策略或执行权限。

至少实现一个 Fake Provider；真实厂商 adapter 放在可选依赖或独立模块中，核心安装不应因其缺失
而失败。

##### 5.4 Middleware 协议
Middleware 应围绕一次 Agent/Tool/LLM 调用，不复制 Executor 的调度、重试和 checkpoint：

```python
class Middleware(Protocol):
    async def before(self, request: Invocation) -> Invocation: ...
    async def after(self, request: Invocation, response: Any) -> Any: ...
    async def on_error(self, request: Invocation, error: BaseException) -> Any: ...
```

第一版内置：

- 结构化调用日志/指标 middleware；
- 工具 allowlist middleware；
- 工具速率限制 middleware；
- 输入输出大小限制 middleware；
- 脱敏 middleware。

组合语义必须固定并测试：before 按注册顺序执行，after 按逆序执行；异常默认向上抛出，只有
显式 middleware 才能转换错误；middleware 不得静默修改状态；同一 middleware 不得因重试被
错误地注册多次。`run_node` 仍是节点级 timeout/retry 的唯一来源。

#### 6. 与现有框架的衔接
##### 阶段 4 可靠性
- Tool/LLM 的临时网络、429/5xx 和明确 transient 错误映射为 `RetryableError`；
- 认证失败、参数校验失败、allowlist 拒绝和 schema 错误默认不可重试；
- timeout、caller cancellation 和底层同步任务未终止的状态必须进入 AttemptRecord；
- middleware 不能在内部再实现一套 retry，避免重试次数乘法膨胀。

##### 阶段 5 Checkpoint 与幂等
- 工具/LLM 请求的 provider、tool version、参数 schema 和输入摘要进入兼容性元数据；
- 有副作用工具必须通过 `SideEffectSink` 或业务侧唯一键保护，不能仅依赖 `ToolSpec.idempotent=True` 的声明；
- LLM 请求默认不作为外部副作用写入 checkpoint；若缓存响应，缓存键必须包含 provider、model、版本、规范化请求和安全策略版本；
- Checkpoint 仍只由 Executor 管理，工具和 middleware 只能通过 `ToolContext` 使用受控接口；
- EventBus 的调用事件只是观测信息，恢复不能依赖事件是否送达。

##### 后续 VulnTell
阶段 6 只提供通用能力。NVD/CNVD 适配、漏洞字段、请求限速策略、报告提示词和指标计算全部
放入阶段 7，并通过 fixture 验证。LLM 可以解释或生成报告，但不能直接改变确定性漏洞评分。

#### 7. 推荐任务拆分
##### Task 0：阶段 5 发布收尾与协议冻结（已完成）
关闭阶段 5 发布门禁，补齐 checksum、并发序号、幂等 claim、运行状态和恢复边界测试；更新
公共 API 状态。随后冻结 ToolSpec、ToolResult、Provider、Middleware 的字段和版本策略，
产出一份最小协议 fixture。本任务已完成。

##### Task 1：Tool 领域模型与 Registry
实现 ToolSpec、ToolContext、ToolResult、ToolError、Registry 注册/查找/重复检测和公共导出。
先使用纯确定性工具，不接网络和外部数据库。

##### Task 2：参数/结果校验与同步异步适配
实现 Pydantic 输入输出校验、同步函数线程适配、异步函数调用、取消和错误映射。补充大输入、
非法输出、同步阻塞和取消清理测试。

##### Task 3：Tool 安全策略
实现 allowlist、大小限制、超时、并发/速率限制、敏感字段脱敏和副作用声明检查。默认策略
必须拒绝未登记工具、shell、任意 URL 和任意文件路径。

##### Task 4：LLM 抽象与 Fake Provider
实现 ChatMessage、LLMRequest、LLMResponse、Usage、Provider 错误和 Fake Provider；覆盖结构化
输出校验、工具调用请求校验和无 API Key 离线运行。

##### Task 5：可选 Provider Adapter
选择一个独立的可选适配器验证协议映射，隔离厂商 SDK、认证和原始响应。默认测试只使用 Fake
Provider；真实网络 smoke test 若需要，必须单独标记且不进入默认 CI。

##### Task 6：Middleware 组合器与内置实现
实现 Agent/Tool/LLM 调用包装、顺序/逆序钩子、异常传播、日志脱敏、限流和统计。验证与
`run_node` 的 retry/timeout 不重复计数。

##### Task 7：Runtime、EventBus、Checkpoint 元数据衔接
扩展 `Runtime`/`ToolContext` 的最小只读能力，发布工具/LLM 调用事件，补充版本和输入摘要；
不得把原始 prompt、密钥或完整漏洞描述无控制地写入 report/checkpoint。

##### Task 8：示例、文档和阶段发布
提供完全离线的工具 Agent、Fake LLM Agent 和 middleware 示例；更新 README、`API.md`、
`DESIGN.md`、`ROADMAP.md`；执行全量测试、类型检查和依赖最小安装验证，形成阶段 6 独立提交。

#### 8. 测试要求
至少新增 30 个有意义的离线测试，并保留阶段 1～5 全部回归：

##### Tool
- [ ] 工具注册、重复版本、未注册查找和 allowlist 拒绝；
- [ ] 合法/非法输入和输出 schema 校验；
- [ ] 同步工具在线程中执行，事件循环不被阻塞；
- [ ] 异步工具结果、异常、超时和调用方取消；
- [ ] 429/5xx 可重试，认证/参数/schema/权限错误不可重试；
- [ ] 限流、并发上限、输入输出大小和脱敏；
- [ ] 副作用工具要求幂等策略，重复 execution key 不重复写入。

##### LLM
- [ ] Fake Provider 在无 API Key、无网络时稳定返回；
- [ ] 请求参数、消息和响应 schema 校验；
- [ ] provider/model/version 进入元数据且不泄露凭据；
- [ ] provider 错误正确映射到可靠性错误分类；
- [ ] LLM 请求的工具名/参数再次经过 Registry 校验；
- [ ] 恶意文本不能改变 allowlist 或执行权限；
- [ ] 可选 adapter 缺失时核心仍可安装和导入。

##### Middleware 与集成
- [ ] before 顺序、after 逆序和异常传播；
- [ ] middleware 不重复注册、不直接修改 State；
- [ ] middleware 与 retry/timeout/cancellation 的调用次数一致；
- [ ] EventBus 事件失败不改变工具结果或核心状态；
- [ ] 工具 Agent 能在顺序 Graph 和并发 Graph 中运行；
- [ ] checkpoint 恢复后工具版本不兼容会明确拒绝；
- [ ] 全量测试、类型检查、导入检查和最小依赖安装通过。

所有默认测试必须离线、无真实 API Key、无真实 LLM、无漏洞源和无生产副作用。真实网络
验证只作为显式 smoke test，不能成为阶段验收的必要条件。

#### 9. 量化验收标准（已满足）
阶段 6 同时满足以下条件才算完成：

1. 阶段 5 发布门禁已关闭，阶段 5 改动已形成可追踪提交；
2. 新增离线测试不少于 30 个，阶段 1～5 原有测试全部通过；
3. Tool 输入/输出 schema 校验覆盖率达到 100%（所有公开 invoke 路径均经过校验）；
4. 未注册工具、未授权工具、越过大小限制和非法工具参数均被拒绝且有结构化错误；
5. 同步、异步工具均能执行；同步工具不直接阻塞事件循环，取消和超时有明确报告；
6. `run_node` 的重试次数、timeout 次数和 Tool/LLM middleware 统计不发生重复计数；
7. Fake Provider 在无网络和无 API Key 环境下稳定运行，LLM 核心协议不导入厂商 SDK；
8. LLM 结构化输出和工具调用参数均经过 schema/allowlist 校验，恶意文本不能提升权限；
9. 同一副作用 execution key 的并发/重放测试只产生一次受保护写入；
10. README、`DESIGN.md`、`API.md`、`ROADMAP.md` 和本文件的实现状态一致；
11. 默认安装不要求 LLM 厂商依赖，`python -m pytest -q`、类型检查和离线示例全部通过；
12. 不引入 VulnTell 业务模型，不执行漏洞利用、PoC、资产探测或未经授权的远程操作。

#### 10. 完成定义（已完成）
```text
阶段 5 发布门禁关闭
        ↓
Tool 协议、Registry 和 schema 校验
        ↓
同步/异步执行、超时取消与安全策略
        ↓
LLM Provider 抽象与 Fake Provider
        ↓
Middleware 组合与可靠性衔接
        ↓
Checkpoint/EventBus 元数据和脱敏
        ↓
离线示例、测试、类型检查和文档发布
```

阶段 6 完成后，框架具备可控的工具调用和可替换 LLM 扩展能力；只有到阶段 7 才开始实现
VulnTell 的真实数据源 Agent、标准化、持久化、聚合和报告流程。

#### 11. 建议提交节奏
```text
fix(phase5): close checkpoint release gates
test(phase5): add corruption and concurrent idempotency cases
design(phase6): freeze tool provider middleware contracts
feat(tools): add tool models and registry
feat(tools): add schema validation and sync async adapter
feat(tools): add allowlist timeout rate limit and redaction
feat(llm): add provider protocol and fake provider
feat(llm): add optional provider adapter
feat(middleware): add composable invocation middleware
feat(runtime): expose safe tool and llm context
test(phase6): cover offline tool llm middleware contracts
docs: document phase-6 extension semantics
```


<a id="phase-doc-phase7"></a>

## 原文：PHASE7.md

### 阶段 7：VulnTell 纵向示例实施计划（已完成）
> **实施约束：** 本阶段首先冻结数据集、字段和指标定义，再开始编写 Agent。下游 Agent 不得
> 在没有 fixture、验收样例和版本号的情况下接入真实网络源或 LLM。

#### 1. 阶段定位
阶段 1～6 已完成：`magent` 具备类型化 State、DAG 编排、并发 fan-out/fan-in、可靠性策略、
Checkpoint/恢复/幂等、Tool Registry、可选 LLM Provider 和 Middleware。阶段 7 已完成并提交；
当前全量离线测试为 211 个且全部通过。

阶段 7 不再扩展框架通用能力，而是使用现有 `magent` 实现一个可复现的 VulnTell 纵向示例，
验证框架能否支撑真实业务流程：多源漏洞情报采集、标准化、持久化、聚合、质量评估和报告生成。
业务代码必须位于 `examples/vulntell` 或独立业务包，不得把 CVE、NVD、CNVD、CVSS 等领域模型
加入 `src/magent` 核心。

#### 2. 当前基线审视
##### 已具备
- `BaseAgent`、`AgentResult`、Pydantic State 和状态合并；
- 条件路由、并发分支、join、reducer 和失败传播；
- 节点超时、显式重试、取消和结构化执行报告；
- SQLite Checkpoint、恢复、稳定 execution key 和 `SideEffectSink`；
- schema 校验的同步/异步 Tool、allowlist、限流、超时和脱敏；
- `FakeProvider`、可选 OpenAI adapter 和 Middleware；
- 离线示例、211 个测试和已提交的阶段 1～7 实现。

##### 已交付
- `examples/vulntell` 领域模型、固定 NVD/CNVD fixture 和来源适配器；
- 确定性标准化、质量告警、跨源 CVE 去重和冲突可追溯；
- 业务 SQLite schema、事务写入、稳定唯一键和幂等副作用协议；
- 并发、可恢复、可处理部分来源失败的 VulnTell Graph；
- 固定数据集/时间窗口/版本元数据、确定性指标和 JSON/Markdown 报告；
- FakeProvider 解释边界、安全边界、恢复质量和端到端离线测试。

固定数据集和指标定义已冻结。尚未完成的“可重放评测、统一 trace、性能基准和参考框架
对比”属于阶段 8，不应倒填为阶段 7 的已交付内容。

#### 3. 阶段目标
完成后应能够离线运行一条完整的 VulnTell DAG：

```text
NVD Fixture ─────┐
                 ├→ Normalize → Deduplicate → Persist
CNVD Fixture ────┘                         ↓
                                  Aggregate → Evaluate → Report
```

目标包括：

1. 将多个来源的原始漏洞记录转换为统一的来源观察模型；
2. 区分“同一漏洞实体”和“不同来源的观察记录”，保留原始数据可追溯性；
3. 通过显式幂等键实现重复运行不重复写入；
4. 在一个来源失败时保留可用结果，并在报告中明确失败来源和数据缺口；
5. 使用确定性规则计算覆盖量、时效性、完整性、维护性、可验证性、相关性和相对独立性等指标；
6. 让 LLM 只负责可选的文字解释或报告润色，不能修改确定性评分；
7. 使用固定 fixture 离线重放，保证相同数据集、窗口和版本得到相同结果；
8. 形成可以展示框架并发、恢复、幂等和扩展能力的最小业务样例。

#### 4. 范围与非目标
##### 4.1 本阶段包含
- `examples/vulntell/models`：标准漏洞、来源观察、指标快照、报告和运行元数据；
- `examples/vulntell/fixtures`：脱敏、固定版本、可审计的 NVD/CNVD JSON 样本；
- `examples/vulntell/sources`：fixture adapter，以及隔离的真实 HTTP adapter 接口；
- `examples/vulntell/agents`：采集、标准化、去重、持久化、聚合、评估和报告 Agent；
- 业务 SQLite 表和幂等写入；
- 使用 `GraphBuilder` 的顺序/并发 DAG；
- 部分来源失败、Checkpoint 恢复和重复执行测试；
- 确定性指标计算、报告 JSON/Markdown 输出和离线 CLI；
- 业务层与 `magent` 核心的边界测试。

##### 4.2 本阶段不包含
- 自动漏洞扫描、资产探测、漏洞利用、PoC 执行或攻击验证；
- 默认访问真实 NVD/CNVD 网络接口；
- 把历史论文数据直接宣称为当前真实统计结论；
- 让 LLM 决定漏洞评分、数据去重、时间窗口或来源排名；
- 自动抓取引用 URL、执行网页脚本或处理不受信任的远程代码；
- 分布式采集、消息队列、实时流处理和多租户服务；
- 完整 Web 前端和生产级数据仓库。

#### 5. 业务模型设计
##### 5.1 原始记录与标准实体分离
必须至少保留以下三层对象：

```text
RawSourceRecord       来源原始载荷，保留 hash、source、record_id、observed_at
SourceObservation     某来源对某漏洞的标准化观察
CanonicalVulnerability跨来源归并后的漏洞实体
```

`SourceObservation` 至少包含：

```text
source
source_record_id
cve_id
published_at
modified_at
source_added_at
observed_at
raw_payload_hash
raw_payload_ref
normalized_fields
parser_version
schema_version
```

统一使用带时区的 UTC 时间。原始载荷可存文件 fixture 或业务表引用，不能把未经限制的完整
远程响应直接塞入 State、日志或 LLM prompt。

##### 5.2 标准化字段
首版只实现能够由 fixture 稳定验证的字段：

- CVE 标识和别名；
- 标题、描述和语言；
- 发布时间、更新时间和来源加入时间；
- CVSS 版本、向量、分数和严重性；
- CWE、受影响产品/版本的规范化表达；
- 引用 URL、引用类型和验证状态；
- 来源、解析器版本、原始记录标识和数据质量告警。

字段缺失、格式非法和语义不确定必须产生结构化质量问题。不得用默认值掩盖“缺失”和“无效”
的区别。

##### 5.3 去重和匹配
首版优先采用可解释规则：

1. 合法 CVE ID 作为强匹配键；
2. 来源记录 ID 作为来源内幂等键；
3. 无 CVE ID 的记录进入待匹配集合，不直接强行合并；
4. 模糊匹配必须保留候选、规则版本和置信等级，不能静默覆盖；
5. 同一字段冲突保留各来源值，由聚合层按明确优先级或字段策略处理。

去重结果必须可以由输入记录、匹配规则版本和 parser version 重新计算。

#### 6. 业务 Graph 与执行语义
##### 6.1 推荐流程
```text
source_nvd ─────┐
                ├→ normalize_nvd ─┐
source_cnvd ────┘                 ├→ deduplicate → persist
                └→ normalize_cnvd ┘                  ↓
                                           aggregate → evaluate → report
```

NVD/CNVD 采集和标准化属于独立分支，使用阶段 3 的分支隔离和 join reducer。分支不能直接修改
另一个来源的中间列表；join 后才进行跨源合并。

##### 6.2 部分失败
业务层不应简单复用框架的 `fail_fast` 作为最终产品策略。首版可采用：

- 采集分支失败：保留其他来源，记录 `source_status=failed` 和错误摘要；
- 标准化单条记录失败：跳过该记录并记录质量告警，不丢弃整个来源；
- 去重/持久化 schema 错误：停止运行，避免产生不可信报告；
- 指标样本不足：输出 `insufficient_data`，不进行无依据排名；
- 报告生成失败：保留结构化指标和机器可读 JSON，文字报告标记失败。

部分失败语义必须体现在 State 和最终报告中，不能只写日志。

##### 6.3 Checkpoint、恢复与幂等
- 每个采集/标准化分支使用稳定 `workflow_version` 和节点 `version`；
- 长耗时或有副作用节点使用 `SqliteCheckpointStore`；
- 业务写入通过业务唯一键与 `SideEffectSink` 共同防止重复；
- 恢复后已提交分支不得重复执行，未提交分支可以重放；
- 真实来源 adapter 的请求重试必须遵守阶段 4 的 timeout、retryable error 和限流策略；
- 远程请求结果只能在成功校验后进入业务 State；
- EventBus 仅用于观测，不能作为业务数据源或恢复依据。

#### 7. 指标与评估设计
##### 7.1 时间窗口和版本
每次评估必须记录：

```text
dataset_id
dataset_version
window_start / window_end
observed_at
parser_version
deduplication_version
metric_version
framework_version
sample_counts
source_status
```

论文历史数据只能作为 baseline 或 fixture 来源，不得直接作为当前运行结果。所有时间计算
使用 UTC，并明确是发布时间、更新时间、来源加入时间还是系统观测时间。

##### 7.2 首版确定性指标
- 数据量：记录数、唯一漏洞数、更新记录数；
- 时效性：观测时间与来源时间的延迟分布；
- 完整性：必需字段的存在率与有效率分开计算；
- 维护性：窗口内更新频率和间隔分布；
- 可验证性：有效引用率、可回溯字段比例；
- 相关性：根据预先声明的技术栈/行业画像计算匹配率；
- 相对独立性：当前观测范围内的首次观察比例，不解释为真实原创率。

指标函数必须是纯函数或依赖显式输入，不读取系统当前时间、随机数或网络。CISA KEV 等职责
不同的数据源若加入后，应使用专门指标，不能直接与 NVD/CNVD 做同口径排名。

##### 7.3 LLM 使用边界
LLM 只可用于：

- 对结构化指标生成自然语言解释；
- 把已验证字段组织成报告草稿；
- 对数据质量告警生成辅助说明。

LLM 不得修改 canonical entity、去重结果、基础指标、最终排名或来源状态。LLM 失败时必须仍
能输出结构化报告；Fake Provider 用于默认离线测试。

#### 8. 数据库与安全要求
业务数据库至少包含：

```text
raw_source_records
source_observations
canonical_vulnerabilities
metric_snapshots
evaluation_runs
quality_issues
```

关键唯一约束建议包括：`(source, source_record_id)`、`cve_id`、`(dataset_id, window, metric_version)`。
写入必须使用参数化 SQL、事务和明确的 schema version。重复导入不能新增逻辑重复记录。

安全要求：

- 外部漏洞文本一律视为不可信内容，经过 LLM 前必须隔离并限制长度；
- 默认不抓取引用链接，防止 SSRF 和任意内容注入；
- 不执行外部 PoC、命令、脚本或动态导入；
- API Key 不进入 fixture、State、checkpoint、报告或日志；
- 业务 SQLite 文件权限和脱敏责任在文档中明确；
- 真实网络 adapter 与离线 fixture adapter 分离，默认 CLI 只使用 fixture。

#### 9. 推荐任务拆分
##### Task 0：业务边界和数据集冻结
整理论文材料中可复用的字段、时间窗口和指标定义；确定 fixture 许可证、来源说明、数据集 ID、
版本和脱敏规则。不得把论文历史结论直接写成运行结果。

##### Task 1：领域模型与 fixture
实现 Pydantic 领域模型、JSON fixture、schema 版本和加载器。覆盖缺失字段、非法时间、重复
source record 和未知字段策略。

##### Task 2：来源适配器
实现统一 SourceAdapter 协议和 NVD/CNVD fixture adapter；定义真实 HTTP adapter 的隔离接口，
但默认不联网。记录来源状态、解析错误和原始载荷 hash。

##### Task 3：标准化与质量问题
实现日期、CVSS、CWE、引用和受影响产品的确定性解析；区分 missing、invalid、ambiguous，
生成结构化 `QualityIssue`。

##### Task 4：去重、聚合与持久化
实现 CVE 强匹配、待匹配集合、字段冲突保留、跨源聚合和业务 SQLite schema。使用唯一键、
事务和 `SideEffectSink` 验证重复运行幂等。

##### Task 5：VulnTell Graph
使用 `GraphBuilder` 构造采集→标准化→join→去重→持久化→评估→报告流程；验证分支隔离、
部分失败、checkpoint 恢复、节点版本和最终状态可追溯。

##### Task 6：指标与报告
实现固定窗口、指标版本、样本量门槛、CISA 等不同职责源的扩展位和 JSON/Markdown 报告。报告
必须同时包含数据集、版本、窗口、失败来源、质量告警和计算版本。

##### Task 7：可选 LLM 解释
用 Fake Provider 为结构化指标生成可重复解释；验证 LLM 不能修改确定性结果，Provider 失败时
报告仍可生成。真实 Provider 只作为显式 smoke test。

##### Task 8：CLI、测试和发布
提供 `python -m examples.vulntell` 或等价离线 CLI；补充边界、安全、恢复和性能测试；更新
README、`API.md`、`DESIGN.md`、`ROADMAP.md`，形成阶段 7 独立提交。

#### 10. 测试要求（验收记录）
阶段 7 已新增 43 个有意义的离线测试，并保留阶段 1～6 全部回归；以下清单均已完成：

##### 数据和标准化
- [x] fixture 加载、版本和许可证元数据校验；
- [x] 合法/非法 CVE、时间、CVSS、CWE 和引用解析；
- [x] 缺失、无效、歧义字段分别产生对应质量问题；
- [x] 原始记录 hash 稳定，重复 source record 可识别；
- [x] 不同来源同一 CVE 能合并，缺少 CVE 的记录不被强行合并；
- [x] 字段冲突可追溯且遵守声明的聚合策略。

##### Graph、恢复和持久化
- [x] NVD/CNVD 分支并发执行，分支状态互不污染；
- [x] 一个来源失败时仍生成部分结果和失败摘要；
- [x] join 等待成功分支并正确处理部分失败语义；
- [x] 中断后从最近成功 checkpoint 恢复，已提交节点不重跑；
- [x] 重复运行不产生重复 observation、entity 和 metric；
- [x] 业务唯一键、execution key 和 SQLite 事务共同生效；
- [x] schema/version 不兼容时明确拒绝恢复。

##### 指标、报告和 LLM 边界
- [x] 固定窗口和 fixture 下指标结果可重复；
- [x] 样本不足返回 `insufficient_data`，不输出虚假排名；
- [x] 指标版本、数据集版本和窗口出现在报告中；
- [x] LLM 解释失败不影响结构化报告；
- [x] LLM 输出不能修改评分、去重或来源状态；
- [x] Fake Provider 无网络、无 API Key 时稳定运行。

##### 安全和质量
- [x] 恶意漏洞描述不会改变工具 allowlist 或执行权限；
- [x] 默认 CLI 不发起网络请求、不抓取引用、不执行命令；
- [x] 日志、State、checkpoint 和报告不包含 API Key；
- [x] 业务包不被 `magent` 核心导入，核心无漏洞领域依赖；
- [x] 全量测试、类型检查、导入检查和离线 CLI 通过。

#### 11. 量化验收标准
阶段 7 已满足以下条件并完成发布：

1. 新增离线测试不少于 40 个，阶段 1～6 全部回归通过；
2. 至少包含 NVD/CNVD 两个来源、一个并发 Graph、一个 join 和一个可恢复中断场景；
3. 固定 fixture、窗口和版本下，连续两次运行的结构化报告逐字段一致；
4. 重复运行后业务唯一记录数量不增加，重复副作用写入次数为 0；
5. 单一来源失败时仍能生成部分报告，并明确记录失败来源和质量缺口；
6. 已提交 checkpoint 的节点恢复调用次数为 0，恢复结果与无中断基线一致；
7. 指标计算为确定性规则，样本不足不进行无依据排名；
8. LLM 仅产生解释文本，不能修改任何确定性实体、指标或排名；
9. 默认 CLI 不访问网络、不需要 API Key、不执行漏洞利用或外部命令；
10. 报告记录 dataset、window、parser、deduplication、metric 和 framework 版本；
11. `magent` 核心不导入 VulnTell 代码，业务代码仅通过公开 API 使用框架；
12. README、`DESIGN.md`、`API.md`、`ROADMAP.md` 和本文件实现状态一致。

#### 12. 完成定义
```text
冻结数据集、字段和指标定义
        ↓
领域模型与离线 fixture
        ↓
来源适配与确定性标准化
        ↓
跨源去重、聚合与幂等持久化
        ↓
并发/可恢复 VulnTell Graph
        ↓
确定性指标与可追溯报告
        ↓
可选 LLM 解释与安全边界
        ↓
离线 CLI、测试、文档和阶段发布
```

阶段 7 完成后，才进入阶段 8 的框架与业务评测、性能基准和对比实验。阶段 8 必须使用阶段 7
冻结的数据集和版本，不在评测过程中临时改变指标或样本。

#### 13. 建议提交节奏
```text
design(phase7): freeze VulnTell dataset and metric boundaries
feat(vulntell): add domain models and offline fixtures
feat(vulntell): add source adapters and normalization
feat(vulntell): add quality issues and deterministic deduplication
feat(vulntell): add sqlite persistence and idempotent writes
feat(vulntell): build concurrent recoverable graph
feat(vulntell): add metrics and structured reports
feat(vulntell): add optional FakeProvider explanations
test(vulntell): cover recovery quality and security boundaries
docs: document phase-7 VulnTell vertical example
```


<a id="phase-doc-phase8"></a>

## 原文：PHASE8.md

### 阶段 8：评测、可观测性与对比实验实施计划（已完成）
> **状态：** 已完成并提交。本文保留实施约束、任务拆分和验收标准，并补充实际交付结果。
> 阶段 8 只在现有执行语义之上增加观测与实验能力；任何改变调度、状态合并、重试、取消、
> Checkpoint 或 VulnTell 确定性指标含义的改动，都必须另立设计并暂停本阶段。

#### 1. 当前基线
阶段 1～7 已完成，阶段 8 已完成并提交。阶段 7 最近相关提交为
`80d7156 docs: document phase-7 VulnTell vertical example`。
当前基线如下：

- `magent` 已支持 Agent、类型化 State、顺序/DAG Graph、fan-out/fan-in、reducer 和并发限制；
- 已支持超时、重试、取消、错误策略、EventBus、SQLite Checkpoint、恢复和稳定幂等键；
- 已支持 Tool Registry、可插拔 LLM Provider、离线 FakeProvider 和 Middleware；
- `examples/vulntell` 已完成离线纵向流程：多源 fixture 采集→标准化→质量告警→去重→持久化→
  可恢复并发 Graph→指标→JSON/Markdown 报告；
- 阶段 8 完成时全量测试为 250 passed；随着后续 VulnTell 来源、批次和存储测试加入，当前全量测试为 **427 passed**，
  默认测试不依赖网络、API Key 或真实 LLM；
- 阶段 7 已冻结数据集、时间窗口、解析器版本、去重版本和指标版本，本阶段不得私自替换。

阶段 8 已交付统一 trace/span/run metadata、实验配置与结果 schema、串行/并行 benchmark、
恢复和失败路径的统一观测、VulnTell 质量评测，以及可审计的参考框架不可比记录。阶段 9 的发布
工程化收口属于后续工作。

#### 2. 阶段目标
1. 建立可选、脱敏、有界的 Trace/Span/RunSummary 观测契约；
2. 记录节点等待、执行、attempt、重试、超时、取消、失败、Checkpoint 和恢复信息；
3. 建立固定配置驱动、离线可重复、原始结果可重放的实验运行方式；
4. 以串行执行作为基线，测量并行度、吞吐量、失败恢复和 Checkpoint 开销；
5. 评估 VulnTell 标准化、去重、指标和报告质量，不把小样本事实夸大为普遍结论；
6. 在等价场景下记录 LangGraph、AutoGen、CrewAI 等参考项目的版本、配置和结果，为设计讨论
   提供材料，不把它们变成 `magent` 运行时依赖。

#### 3. 非目标
- 不引入分布式调度、远程 tracing 服务、消息队列或生产级监控平台；
- 不修改既有执行语义，不以 benchmark 为理由改变默认重试、并发、超时或指标定义；
- 不默认联网、不调用真实 LLM、不抓取漏洞引用 URL、不使用未授权真实漏洞数据；
- 不实现自动框架排名、统计显著性结论或“通用性能领先”宣传；
- 不把论文历史数据直接当作当前系统观测结果；
- 不将 LangGraph/AutoGen/CrewAI 的内部对象或源码复制到本仓库。

#### 4. 观测设计
##### 4.1 数据模型
建议在 `src/magent/observability/` 实现以下纯数据模型和协议；具体字段名在实现前冻结，避免
下游 Agent 各自定义格式：

```text
Trace
 ├─ trace_id / run_id
 ├─ workflow_id / workflow_version / state_schema_version
 ├─ started_at / finished_at / status
 └─ metadata（脱敏、有界）

Span
 ├─ span_id / trace_id / parent_span_id
 ├─ node_id / agent_name / attempt
 ├─ queued_ms / duration_ms / status
 ├─ error_type / retry_reason / cancellation_reason
 └─ metadata（脱敏、有界）

RunSummary
 ├─ trace_id / run_id
 ├─ node、success、failure、cancelled 计数
 ├─ retry_count / peak_concurrency
 ├─ checkpoint_writes / recovery_count / replayed_nodes
 ├─ duration_ms
 └─ resource_samples（未采集时为 null，而不是 0）
```

约束：

- 一个完整 run 对应一个 Trace；一次节点 attempt 对应一个 Span；重试必须产生独立 attempt
  Span，并通过相同 node 标识和明确 attempt 序号关联；
- `run_id`、`trace_id`、workflow/node 版本在同一次执行中保持一致；恢复运行必须保留原 run
  关联，并显式标识 `resumed`、`resumed_from_seq` 和 `replayed_nodes`；
- 时间使用 UTC ISO-8601 做持久化，耗时使用注入的单调时钟计算；开始/结束缺失必须可表达；
- metadata 必须经过现有脱敏规则并限制大小、层级和集合长度；禁止写入 API Key、完整原始漏洞
  描述、未经验证的远程响应和大块 State；
- Trace 记录器只能消费 EventBus、ExecutionReport 和 Checkpoint 历史，不能修改 State，也不能
  作为恢复依据；关闭记录器后，业务结果应与未启用观测一致；
- 导出格式首选 JSONL（逐条 Trace/Span）和 JSON（RunSummary），实验聚合再输出 CSV/Markdown。

##### 4.2 采集边界
优先复用已有生命周期事件和 `ExecutionReport`，不得在 Agent、Executor 和 benchmark runner 中
分别复制一套计时/重试计数逻辑。对同一指标规定唯一来源：

| 信息 | 首选来源 |
|---|---|
| 节点 attempt、错误、重试、超时、取消 | attempt lifecycle events / StepRecord |
| 节点总耗时和等待耗时 | Executor 注入的单调时钟与调度记录 |
| 最终成功与节点汇总 | ExecutionReport |
| Checkpoint 写入、恢复序号、重放节点 | Checkpoint history / resume report |
| 峰值并发 | Executor 已有并发统计 |
| 业务质量指标 | VulnTell 的确定性 metrics 模块 |

若不同来源发生冲突，结果应标记不一致并失败测试，不能静默选择一个值。

#### 5. 实验协议
##### 5.1 冻结配置
实验配置至少包括：

```text
experiment_id / scenario_id
dataset_id / dataset_version
window_start / window_end / observed_at
parser_version / deduplication_version / metric_version
framework_version / Python_version / dependency_versions
concurrency / timeout / retry policy / checkpoint enabled
repetitions / seed / sample_threshold
```

阶段 7 VulnTell fixture、窗口和版本作为默认数据集；任何变更必须产生新的 dataset/version，
不得覆盖旧结果。每次运行保存配置快照、原始观测和聚合结果。

##### 5.2 场景矩阵
至少实现以下离线场景：

| 场景 | 目的 | 主要输出 |
|---|---|---|
| sequential baseline | 建立无并行基线 | 总耗时、节点耗时、正确性 |
| parallel DAG | 验证 fan-out/fan-in 收益和上限 | 并发度、吞吐量、峰值并发 |
| retry/timeout/cancel | 观测可靠性开销和终态 | attempt、重试、失败原因 |
| checkpoint recovery | 验证恢复与重放成本 | 恢复耗时、重放节点、结果一致性 |
| VulnTell quality | 评估标准化/去重/报告质量 | precision/recall/F1（有标注时）、完整率 |

至少测试 3 个并发度；每个配置至少重复 5 次，保存 n、均值、中位数、p95、最小值和最大值。
计时结果必须同时保存正确性断言，性能更快但结果错误的运行无效。

##### 5.3 公平对比原则
参考框架对比必须明确记录：精确版本或 commit、Python/依赖版本、运行环境、图结构、输入数据、
并发度、重试/超时配置、预热和计时范围、是否包含序列化/初始化成本。无法建立等价条件时，输出
`not_comparable` 和差异说明，不输出排名。参考框架不可用、版本冲突或网络不可用时，不阻塞
`magent` 本地 benchmark；但报告必须记录缺失项。

#### 6. 实施任务拆分
##### Task 0：冻结实验协议与目录
- 确认上述字段、状态枚举、时间单位、统计方法和样本门槛；
- 设计 `benchmarks/`、结果输出目录和忽略规则，禁止提交临时数据库、缓存和密钥；
- 记录阶段 7 dataset/window/parser/dedup/metric 版本；
- 产出：本文件补充的 schema 变更记录或独立 `benchmarks/README.md`。

##### Task 1：Trace/Span/RunSummary 模型
- 实现 Pydantic/不可变数据模型、校验、JSONL/JSON 序列化和脱敏/大小限制；
- 明确父子关系、attempt 关联、恢复字段和未采集资源字段；
- 不把具体存储后端、OpenTelemetry SDK 或云服务设为核心依赖。

##### Task 2：接入现有执行生命周期
- 通过 EventBus、ExecutionReport 和 Checkpoint history 生成统一记录；
- 覆盖顺序图、并行 DAG、失败、重试、超时、取消、恢复和幂等重放；
- 验证观测启用/关闭时最终 State、报告成功性和业务副作用一致。

##### Task 3：实验 runner 与串行基线
- 实现固定配置加载、环境快照、seed、重复运行和原始结果保存；
- 建立 VulnTell 的顺序执行基线，并定义计时起止点和正确性断言；
- 提供离线 CLI 或等价入口，默认不写入仓库内固定数据库。

##### Task 4：并行与可靠性 benchmark
- 运行至少 3 种并发度，记录吞吐量、峰值并发、等待/执行耗时和结果一致性；
- 运行失败重试、超时、取消和 checkpoint 恢复场景；
- 分离冷启动、框架初始化、业务执行和报告聚合耗时，避免混为一个数字。

##### Task 5：VulnTell 业务质量评测
- 使用阶段 7 冻结 fixture；如增加人工标注真值，必须另设标注版本和覆盖说明；
- 评估标准化字段缺失/无效率、跨源一致性、去重 precision/recall/F1（仅在有真值时）、
  报告字段完整性、部分失败可用性和指标重复性；
- 样本不足输出 `insufficient_data`，不得计算无依据排名。

##### Task 6：参考框架对比记录
- 先完成设计/API/语义对比，再决定哪些参考框架可运行；
- 为每个框架建立隔离 adapter 或实验脚本，禁止污染 `src/magent` 依赖；
- 仅报告同场景可比结果；不可比项保留原因、版本和环境信息。

##### Task 7：结果报告与文档
- 生成机器可读 JSON/JSONL/CSV 和人工可读 Markdown；
- 报告原始样本、聚合统计、失败配置、环境、版本、样本量和限制说明；
- 更新 `README.md`、`../architecture/DESIGN.md`、`../architecture/API.md`、`ROADMAP.md`，必要时补充
  `../evaluation/BENCHMARKS.md`；
- 不把一次本地小样本结果写成项目固定性能承诺。

#### 7. 主要风险与控制措施
| 风险 | 影响 | 控制措施 |
|---|---|---|
| 计时口径不一致 | benchmark 结论失真 | 冻结起止点，区分冷启动/执行/聚合，使用单调时钟 |
| 并发完成顺序造成结果漂移 | 正确性与性能混淆 | 使用显式 reducer/稳定排序；先断言结果一致再统计 |
| EventBus 丢事件或重复消费 | trace 不完整 | 以 report/checkpoint 为权威补全；记录缺失并测试，不把 EventBus 当日志真相 |
| 重试与恢复重复计数 | 失败率和成本虚高 | attempt、node、resume run 分层建模，定义去重键 |
| 观测逻辑反向影响执行 | 引入回归 | observer 只读、可禁用；观测异常隔离并有回归测试 |
| metadata 泄露密钥/漏洞文本 | 安全与合规问题 | 脱敏、长度限制、字段白名单；安全测试和输出扫描 |
| 小样本或 fixture 偏差 | 过度泛化 | 报告 n、数据集和限制；门槛不足标记 `insufficient_data` |
| 参考框架配置不等价 | 不公平对比 | 记录版本和参数；不可比则不排名 |
| 依赖安装/网络不可用 | 阻塞开发 | `magent` 主 benchmark 离线；参考实验隔离、可选、失败可记录 |
| 临时结果污染 Git | 仓库不可复现 | 统一输出目录、`.gitignore`、CI 检查未跟踪产物 |

#### 8. 测试要求
阶段 8 至少新增 **30 个有意义的离线测试**，并保留现有 211 个测试全部回归：

- Trace：Trace/Span 字段校验、run_id 一致、父子关系、attempt 关联、UTC 和单调耗时；
- 完整性：成功、失败、重试、超时、取消、部分并发取消、Checkpoint 恢复和幂等重放均有记录；
- 汇总：节点计数、重试数、峰值并发、恢复次数和报告统计与 ExecutionReport/Checkpoint 一致；
- 安全：密钥、完整外部漏洞文本和超大 metadata 不进入 trace、checkpoint、日志和报告；
- 隔离：关闭 observer 不改变最终 State、报告、调用次数和副作用结果；
- 实验：固定配置重复运行可重放，结果包含数据集/窗口/版本/样本数，统计字段完整；
- 正确性：串行和并行输出一致；不同并发度不改变 VulnTell 确定性指标；
- 质量：有真值才计算 precision/recall/F1；样本不足返回 `insufficient_data`；
- 对比：版本、环境、配置缺失时标记 `not_comparable`，不生成排名；
- 离线：默认 runner 无网络、无真实 LLM、无 API Key，不创建仓库外不可控副作用。

#### 9. 量化验收标准（验收结果）
阶段 8 已满足以下条件并完成发布：

1. 阶段 8 新增离线测试 39 个；随着后续 VulnTell 来源、批次和存储测试加入，当前全量测试为 427 passed；
2. Trace/Span/RunSummary schema、序列化格式和脱敏规则已文档化并有测试；
3. 顺序、并行、失败/重试、超时/取消、Checkpoint 恢复五类场景均可生成结果；
4. 至少 3 种并发度、每种配置至少 5 次重复，并保存原始样本与 n/mean/median/p95/min/max；
5. 观测启用与关闭时，确定性 State、VulnTell 报告和幂等副作用结果一致；
6. 恢复结果与无中断基线一致，已提交节点不重复执行，重试和恢复计数可区分；
7. 每个结果包含 dataset、window、sample count、parser/dedup/metric/framework 版本及环境摘要；
8. VulnTell 质量结果使用固定 fixture；缺少真值或样本不足时明确标记，不输出虚假排名；
9. 参考框架至少完成设计/配置记录；只有满足等价条件的实验才允许展示数值对比；
10. 默认 benchmark 离线运行，不引入必需的 LangGraph/AutoGen/CrewAI 依赖，不泄露敏感信息；
11. README、DESIGN、API、ROADMAP 与阶段 8 实现状态一致，结果不包含临时数据库和缓存产物。

#### 10. 完成定义
```text
冻结实验协议与数据集版本
        ↓
Trace/Span/RunSummary 模型与脱敏
        ↓
接入 EventBus / ExecutionReport / Checkpoint
        ↓
串行基线与离线实验 runner
        ↓
并发、可靠性、恢复和幂等 benchmark
        ↓
VulnTell 质量评测与可比性门槛
        ↓
参考框架记录与限制说明
        ↓
JSON/CSV/Markdown 结果、测试、文档和提交
```

#### 11. 建议提交节奏（已完成）
```text
design(phase8): freeze observability and evaluation protocol
feat(observability): add trace span and run summary models
feat(observability): integrate lifecycle and checkpoint records
feat(benchmarks): add offline runner and sequential baseline
feat(benchmarks): measure parallel reliability and recovery scenarios
test(benchmarks): verify determinism security and comparability gates
docs: publish phase-8 evaluation results and limitations
```

下一阶段为阶段 9：发布、展示与工程化收口，详见 [`PHASE9.md`](PHASES.md#phase-doc-phase9)。


<a id="phase-doc-phase9"></a>

## 原文：PHASE9.md

### 阶段 9：发布、展示与工程化收口实施计划
> **交付对象：** 下游开发 Agent。本文是阶段 9 的实施基线。目标是把已经完成的框架核心、
> VulnTell 示例和阶段 8 评测整理成可安装、可验证、可理解、可展示的 GitHub 项目。
> 本阶段优先完成可复现的源码仓库发布；PyPI 发布和 Web 看板不是默认交付物，必须经过额外
> 范围确认和验收。

#### 1. 当前基线
截至当前工作区：

- 阶段 1～8 已完成；
- `src/magent` 已具备 Agent/State/Result、Graph、并发、EventBus、重试/超时/取消、Checkpoint/
  恢复/幂等、Tools、LLM Provider、Middleware 和只读可观测性；
- `apps/vulntell` 已提供固定 fixture 驱动的多源漏洞情报流程，`examples/vulntell` 保留兼容入口；
- `benchmarks/` 已提供离线场景、VulnTell 质量评测和参考框架对比记录；
- 阶段 9 当前全量测试为 **427 passed**，`mypy src/magent` 已通过；阶段 9 专项发布门禁为 10 个测试；
- 默认流程不需要网络、API Key 或真实 LLM；
- 当前仓库已有 README、API、DESIGN、PHASE1～9、ROADMAP、参考项目对比、许可证、第三方归属、
  GitHub Actions 和正式发布检查清单；
- `pyproject.toml` 已完成阶段 1～8 的项目描述、MIT license 和 `mypy` 开发依赖配置；
- `benchmarks/out` 为生成目录，不应作为普通 Git 提交物。

#### 2. 阶段目标
1. 让新用户能在干净环境中按 README 安装并运行核心示例；
2. 让 GitHub 仓库具备完整的项目定位、架构说明、API 入口、参考分析、限制和许可证信息；
3. 建立自动化质量门禁，确保测试、类型检查、构建和离线示例在提交时持续通过；
4. 固化阶段 8 的实验复现入口、版本信息和结果解释边界；
5. 形成适合 GitHub 展示、论文材料和简历项目描述的最小可交付版本；
6. 明确核心框架、业务示例、benchmark 和未来 Web 看板的边界，避免发布阶段范围失控。

#### 3. 发布范围与非目标
##### 3.1 本阶段包含
- README、API、DESIGN、路线图和阶段文档的事实一致性修订；
- `../architecture/COMPARISON.md`：LangGraph、AutoGen、CrewAI 的设计对比和本项目取舍；
- 许可证、第三方归属、数据集/fixture 来源说明和安全使用说明；
- GitHub Actions CI、干净环境安装验证和离线 smoke test；
- 打包元数据、版本策略、变更日志和发布检查清单；
- 核心示例、VulnTell 示例、benchmark CLI 的最短运行路径；
- 阶段 8 结果和限制说明的归档入口；
- 发布前的敏感信息、生成产物、依赖和文档链接检查。

##### 3.2 本阶段不包含
- 分布式执行、生产级服务化、远程 tracing、消息队列和多租户；
- 默认接入真实 NVD/CNVD、真实 LLM 或任何需要密钥的服务；
- 自动漏洞扫描、PoC 执行、漏洞利用和外部命令执行；
- 不经验证的跨框架性能排名；
- 生产级 Web 看板。若确实需要看板，只做独立的范围评估，不阻塞核心发布；
- 未经许可的数据扩充、论文结论重写或面向生产的安全承诺；
- 未经单独验收的 PyPI 正式发布。

#### 4. 发布物结构
```text
GitHub repository
├── README.md                 # 定位、安装、最短示例和限制
├── CHANGELOG.md              # 版本变更
├── LICENSE                   # 项目许可证
├── THIRD_PARTY_NOTICES.md    # 依赖/参考项目/fixture 归属说明
├── pyproject.toml            # 包元数据与开发工具入口
├── .github/workflows/ci.yml  # 自动质量门禁
├── docs/
│   ├── API.md
│   ├── DESIGN.md
│   ├── COMPARISON.md
│   ├── BENCHMARKS.md         # 阶段 8 结果与复现说明（可选独立文档）
│   └── PHASE1～9.md
├── src/magent/               # 可复用框架核心
├── examples/vulntell/        # 下游业务示例
├── benchmarks/               # 离线评测代码与说明
└── tests/                    # 自动化测试
```

`benchmarks/out/`、数据库、缓存、`.env`、API Key、mypy/pytest 缓存和真实运行日志不属于发布物。

#### 5. 实施任务拆分
##### Task 0：冻结发布范围与版本策略
- 确认本次发布是 GitHub 源码仓库 release，还是同时构建 wheel/sdist；默认选择前者并验证可编辑安装；
- 冻结当前版本号、Python 支持范围、公开 API 范围和兼容性承诺；
- 明确阶段 8 benchmark 结果是示例性本地结果，不是性能保证；
- 为所有后续改动建立变更记录，不在发布前无记录地改变执行语义。

##### Task 1：文档事实统一
- 更新 README 的阶段状态、安装方式、示例命令、目录结构和当前限制；
- 更新 `../architecture/API.md` 的版本范围、稳定 API、阶段 8 实际字段和已知限制；
- 更新 `../architecture/DESIGN.md` 的架构、目录、观测与业务边界；
- 将 `docs/phases/PHASE8.md` 标为已完成，补充实际实现、测试数和结果入口；
- 将本文件和 `ROADMAP.md` 标为阶段 9 当前计划，阶段完成后再切换为已完成；
- 检查所有相对链接、绝对本地链接和命令在干净 checkout 中是否可用。

##### Task 2：参考项目与许可证材料
- 创建 `../architecture/COMPARISON.md`，至少比较 Agent、State、Graph/Workflow、并发、Checkpoint、重试、
  工具/LLM 扩展、可观测性和生态定位；
- 每项参考结论记录来源 URL、项目版本或 commit、查看日期和“借鉴/未采用”的原因；
- 不复制 LangGraph、AutoGen、CrewAI 源码和实现细节；
- 选择并写入本项目许可证，补充 `THIRD_PARTY_NOTICES.md`、fixture 来源、数据许可和引用方式；
- 不把论文历史数据、第三方名称或实验数字写成未经证实的项目优势。

##### Task 3：安装与构建验证
- 修正 `pyproject.toml` 的 description、版本说明和开发依赖声明；
- 决定 `examples/` 和 `benchmarks/` 是源码仓库运行资产还是需要随 wheel 发布，并在 README 中明确；
- 在干净虚拟环境执行 `pip install -e ".[dev]"`、`import magent` 和核心示例；
- 如构建发行包，分别检查 sdist/wheel 内容、安装后的 import 和版本号；
- 确认安装流程不要求 OpenAI SDK、网络或环境变量。

##### Task 4：CI 质量门禁
- 建立 GitHub Actions，至少执行 Python 3.11、3.12、3.13 中项目声明支持的版本；
- CI 至少包含：安装、全量 pytest、`mypy src/magent`、`git diff --check` 等价检查和离线 CLI smoke test；
- 增加网络访问防回归检查，默认测试中禁止真实 HTTP、真实 LLM 和外部命令；
- 检查测试输出、benchmark 输出和数据库不会被意外提交；
- 参考框架依赖作为可选实验，不得成为默认 CI 必需依赖。

##### Task 5：安全、依赖与数据合规
- 扫描仓库中的 API Key、token、私钥、`.env`、数据库和未经许可的原始数据；
- 固化外部漏洞文本不进入日志、Trace、Checkpoint 和报告的测试；
- 审核依赖许可证、可选 OpenAI adapter 的懒加载和供应链风险；
- 明确 fixture 是脱敏/演示数据，报告不得宣称为当前真实情报统计；
- 检查 README 和示例不会诱导用户执行漏洞利用、PoC 或不安全远程抓取。

##### Task 6：示例与展示路径
- 为核心框架提供一个最短可复制示例：Agent → State → Result → 执行报告；
- 为 Graph、Checkpoint/恢复、Tools/LLM/Middleware、VulnTell 和 benchmark 提供明确命令；
- 展示成功、部分来源失败、恢复和 Trace 输出等关键能力；
- 所有默认命令使用 fixture/FakeProvider，失败时给出可定位错误；
- 准备一段项目简介、技术亮点、限制和可量化结果，供 GitHub README、简历和论文材料使用；
- 若增加 Web 看板，必须独立目录、独立依赖和独立验收，不修改核心执行协议。

##### Task 7：版本、变更和发布检查
- 创建 `CHANGELOG.md`，记录阶段 1～8 的主要能力和阶段 9 发布内容；
- 明确 `0.x` 阶段的 API 兼容策略：新增字段可扩展，破坏性变更必须记录；
- 创建发布 checklist，逐项记录测试、安装、构建、文档、许可证、安全和示例结果；
- 创建 Git tag/release 草稿前，确认工作区干净、无敏感文件和无生成产物；
- 发布说明中同时列出已实现能力、未实现能力、离线限制和参考框架不可比边界。

#### 6. 主要风险与控制措施
| 风险 | 影响 | 控制措施 |
|---|---|---|
| 文档与代码/API 不一致 | 用户按文档无法运行 | 以公开 API 和 CI smoke test 为准，发布前逐条验证命令 |
| `pyproject` 与实际版本/功能不一致 | 安装和对外定位错误 | 修正 description、版本和依赖，构建后检查 metadata |
| examples/benchmarks 未进入安装包 | 用户安装后找不到示例 | 明确源码仓库运行策略，必要时增加打包测试，不作隐含承诺 |
| 缺少许可证或归属说明 | 法律和 GitHub 合规风险 | 选择许可证，补充第三方/fixture/参考项目归属 |
| CI 依赖网络或真实服务 | 构建不稳定、泄露凭据 | 默认完全离线，真实 smoke test 独立且不进默认门禁 |
| benchmark 小样本被误读 | 产生不当性能结论 | 保存环境/版本/n，明确不排名和限制，不写固定性能承诺 |
| 发布前偷偷改变执行语义 | 已有用户/测试回归 | 阶段 9只收口和修复发布阻塞问题，功能变更另开阶段 |
| Web 看板范围膨胀 | 延迟核心发布 | 看板独立评审，不作为核心发布前置条件 |
| 敏感日志或生成文件入库 | 凭据/数据泄露 | secret scan、`.gitignore`、发布前文件清单和输出扫描 |
| 只验证当前机器 | 跨平台安装失败 | CI 矩阵和干净环境验证，记录未支持平台 |

#### 7. 测试与验证要求
阶段 9 不以盲目增加单元测试数量为目标，而以“干净环境可安装、可运行、可维护”为目标。至少
完成以下验证：

- 当前 427 个测试全部通过；
- `mypy src/magent` 通过；
- 干净虚拟环境安装 `.[dev]` 成功，`import magent` 和版本读取成功；
- 核心 Agent 示例、Graph 示例、Checkpoint 示例、Tools/LLM/Middleware 示例、VulnTell CLI 和
  benchmark CLI 均成功运行；
- VulnTell 默认、`--no-llm`、部分来源失败、`--trace` 和恢复路径均可验证；
- benchmark 结果包含版本、数据集、窗口、样本数、环境和限制说明，且不产生需提交的临时文件；
- sdist/wheel（若本阶段选择构建）在干净环境安装后，公开核心 API 可导入；
- CI 至少覆盖项目声明支持的 Python 版本；
- 文档链接、代码块命令、许可证、第三方归属和目录说明无明显错误；
- 安全检查确认仓库不含密钥、私钥、数据库、真实漏洞原始数据和未授权版权材料；
- 默认测试不访问网络、不调用真实 LLM、不执行外部命令。

#### 8. 量化验收标准
阶段 9 已满足本地收口条件；正式 GitHub Release 仍以远程 CI、维护者确认和 tag 创建为最后条件。
计划验收条件如下：

1. `README.md` 能指导新用户在干净环境完成安装、核心示例、VulnTell 和 benchmark 运行；
2. 全量测试、类型检查和 CI 在所有声明支持的 Python 版本上通过；
3. 项目元数据、版本号、README、API、DESIGN、ROADMAP 和阶段文档状态一致；
4. `../architecture/COMPARISON.md` 完成，至少覆盖 LangGraph、AutoGen、CrewAI，并记录版本/来源/取舍；
5. LICENSE、第三方归属、fixture 来源/许可和安全边界文件齐全；
6. 默认流程保持离线，不要求 API Key、真实 LLM、参考框架依赖或生产数据库；
7. VulnTell 和阶段 8 benchmark 结果可按固定入口重放，结果限制和样本规模明确；
8. 发布前扫描无密钥、敏感日志、数据库、缓存和未授权数据，Git 工作区干净；
9. 核心包可安装并导入，示例和 benchmark 的归属/安装范围在文档中明确；
10. 发布说明明确列出当前不支持的分布式执行、动态规划、生产 Web 看板和跨框架排名；
11. 若未完成 Web 看板或 PyPI 发布，不得把它们写入“已交付”清单；
12. 至少生成一次候选 release 检查记录，并由维护者确认后才创建正式 tag/release。

#### 9. 完成定义
```text
冻结 GitHub 发布范围与版本策略
        ↓
统一 README/API/DESIGN/路线图事实
        ↓
完成参考项目、许可证与数据归属材料
        ↓
完成干净安装、构建和跨版本 CI
        ↓
完成离线示例、VulnTell 和 benchmark 展示路径
        ↓
完成安全、依赖、敏感信息和生成物审计
        ↓
完成 CHANGELOG、发布清单和限制说明
        ↓
候选 release 验收通过并创建 GitHub release
```

#### 10. 建议提交节奏
```text
design(phase9): freeze release scope and compatibility policy
docs: align README API design and phase status
docs: add framework comparison and third-party notices
chore: finalize package metadata and license files
ci: add clean-install test type-check and offline smoke tests
docs: add examples benchmark reproduction and changelog
test: add release security packaging and documentation gates
release: prepare candidate checklist and GitHub release notes
```

<a id="phase-doc-phase10"></a>

## 阶段 10：MCP 客户端适配（magent 作为 MCP 客户端）

> 方案方向：把外部 MCP Server 暴露的工具“接入” magent 既有 `ToolRegistry` 策略管线，
> 使 Agent 可以像使用本地工具一样调用任意外部 MCP 工具。
> 配套策略见 [`docs/architecture/NETWORK_POLICY.md`](../architecture/NETWORK_POLICY.md)（分层网络策略）。

## 1. 阶段目标

1. 提供一条受策略约束的 MCP 客户端通道：连接外部 MCP Server → 列举工具 → 注册进 `ToolRegistry` → Agent 正常调用；
2. MCP 工具与本地工具在同一套策略下运行：allowlist、I/O 校验、大小限制、并发限制、超时、脱敏、`SideEffectSink` 幂等；
3. MCP 错误与重试语义映射进既有 `ReliabilityPolicy`；取消与进度通知传导进既有 `ToolContext`/`EventBus`；
4. 全部核心测试离线确定性（通过 Fake transport），真实连接 smoke 单独命名。

## 2. 明确不做的内容（禁止事项）

- 不做 MCP **Server**（把 VulnTell/框架暴露给外部客户端）——后续应用阶段，非本阶段；
- 不做 LLM 工具调用环路（`tool_calls` 执行循环）——Phase 11，独立最小闭环；
- 不把 MCP SDK 类型渗入核心协议：SDK 仅在 transport 实现层出现，接口用自有 Protocol 表达；
- 不允许绕过 `ToolRegistry` 直接调用 MCP 工具（包括 allowlist 绕过、spy 旁路）；
- 不让 MCP 引入改变 executor 的调度、重试、状态合并、checkpoint 主语义；
- 默认拒绝 elicitation（人在环请求）：本阶段不提供人的审批交互，server 请求 elicitation 一律返回拒绝错误。

## 3. 实现范围

### 3.1 包结构

```text
src/magent/mcp/
├── __init__.py     # 公共导出；顶层导入不触发 SDK（镜像 llm/openai_adapter.py 模式）
├── spec.py         # McpServerConfig / McpToolSpec / 工具命名（<server>__<tool> 前缀）
├── transport.py    # McpTransport Protocol（薄接缝，隔离 SDK v1/v2 变动）
├── stdio.py        # stdio transport（懒加载 SDK）
├── http.py         # streamable HTTP transport（懒加载 SDK）
├── fake.py         # FakeMcpServer + InMemoryMcpTransport（零网络确定性测试，对标 FakeProvider）
├── schema.py       # JSON Schema（子集）→ pydantic 动态模型；无法覆盖时回退 dict 透传
├── proxy.py        # McpToolProxy —— 将一个 MCP 工具适配为 FunctionTool
├── loader.py       # McpToolLoader —— connect → list_tools → 注册进 ToolRegistry
└── errors.py       # MCP 错误 → 可重试/不可重试 ToolError 分类映射
pyproject.toml      # optional extras: mcp = ["mcp>=1.10,<2"]（v2 beta 期禁用，transport 接缝保留迁移位）
tests/unit/         # 用 Fake transport 的全部测试（默认离线）
tests/contract/     # “MCP 工具必须走 Phase 6 同一策略管线”的契约测试
tests/live/         # 真实 server smoke（marker=live，默认跳过）
```

### 3.2 协议草案

```python
class McpTransport(Protocol):
    async def connect(self) -> None: ...
    async def list_tools(self) -> list[mcp.types.Tool]: ...        # SDK 类型只出现在实现内部
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpCallOutcome: ...
    async def cancel_pending(self, name: str) -> None: ...
    async def close(self) -> None: ...

class McpCallOutcome:   # 有界结果：结构化结果 / 文本内容 / 错误
    ...

class McpToolLoader:
    def __init__(self, registry: ToolRegistry, servers: Sequence[McpServerConfig],
                 *, tool_prefixing: bool = True, allowlist: Sequence[str] | None = None) -> None: ...
    async def load(self) -> McpToolsetSnapshot: ...   # 返回本 run 的工具集 + 指纹
    async def close(self) -> None: ...
```

### 3.3 与既有策略管线的映射

| MCP 概念 | magent 落点 |
|----------|-------------|
| tool 的 `name/description/inputSchema` | `FunctionTool.spec`（name 加 `server__tool` 前缀防撞；schema 转 pydantic input model） |
| 调用（`tools/call`） | `ToolRegistry.invoke(...)` → `McpToolProxy.invoke(args, ctx)` → transport |
| 超时 | registry per-call timeout + magent `TimeoutPolicy` 双层（magent 是硬上限） |
| 错误 | `errors.py` 分类：rate_limited（可重试）/ timeout（可重试）/ transient（可重试）/ auth / forbidden / invalid / permanent（不可重试），映射到 `ToolError*` 子类并在 attempt 事件中保留类别 |
| `notifications/progress` | `ToolContext.emit("tool.mcp.progress", payload)` → EventBus（观测旁路） |
| 取消 | `ToolContext.cancel_event` → proxy 中断等待并调用 transport 取消 |
| elicitation | proxy 返回结构化拒绝错误（不可重试），计数并记录事件 `tool.mcp.elicitation_denied` |
| 副作用声明 | server 无法声明幂等性：凡非纯只读口径的工具（LLM 无法证明只读）按 `side_effect=True` 处理，注册期强制 `idempotent=True`，经由 `SideEffectSink` 的稳定 execution key 保证重复调用只执行一次 |
| 工具集快照 | run 启动时记录 `{工具名, server, 描述指纹}`；resume 时重算指纹，不一致则明确拒绝恢复（不隐式迁移、不猜测） |

## 4. 关键设计决策

1. **SDK 接缝**：官方 `mcp` SDK（pin `>=1.10,<2`；v2 beta 期不随动）只在 transport 实现层出现，切换 SDK/v2 只改 transport；
2. **命名前缀**：`<server_name>__<tool_name>`，复用 registry 既有“重复注册即报错”的防撞语义；
3. **ESchema 覆盖子集**：`schema.py` 先覆盖 MCP 常见 JSON Schema（object/properties/required/基本类型/enum/array/嵌套 object）；遇到未支持结构回退 `dict[str, Any]` 透传并在 spec metadata 标注 `fallback_untyped=True`，不因 schema 解释失败而崩；
4. **安全默认值**：allowlist 默认仅允许显式列出的 server×tool；未声明允许清单时拒绝注册全部（与 Phase 6 “默认最小权限”一致）；HTTP transport 默认关闭、需显式配置（SSRF 面）；
5. **观测**：每次 MCP 调用一条 Span（server、tool、传输类型、延迟、错误类别），原始响应不落 trace（沿用既有脱敏规则）。

## 5. 与网络策略的关系（L2）

- 本模块属 **L2 框架联网扩展**：SDK 函数内懒加载；不使用时零网络行为；默认测试全部离线（Fake transport）；
- 真实连接 smoke 要单独命名 `tests/live/`，显式启用，配置超时与密钥隔离。

## 6. 验收标准

- [ ] `import magent` 与全量默认测试在未安装 `mcp` extra 时通过（核心依赖集不变）；
- [ ] FakeMcpServer 场景：列举→注册→invoke→结果回填 AgentResult 全链路单测通过；
- [ ] allowlist 拒绝未列出的工具；重复注册前缀冲突报错；elicitation 默认拒绝并留事件；
- [ ] 超时/可重试错误经 `ReliabilityPolicy` 正确重试；不可重试错误 fail-fast；attempt 事件带错误类别；
- [ ] side_effect 口径的 MCP 工具经 `SideEffectSink` 幂等（同参数重复调用只执行一次，含恢复重放）；
- [ ] resume 时工具集指纹不一致 → 明确拒绝恢复；
- [ ] contract 测试证明 MCP 工具与本地工具走的是同一 `ToolRegistry.invoke` 路径；
- [ ] 真实 server smoke（如 NVD 相关 MCP server 或官方模型 context 演示 server）作为 `live` marker 测试单独通过记录，不计算进离线门禁。

## 7. 文档同步清单

- README：安装段补充 `mcp` extra 与网络策略链接；
- `docs/architecture/DESIGN.md` §4.6/§7：加入“MCP 属网络扩展层”定位与 elicitation/默认拒绝边界；
- `docs/architecture/API.md`：新增 magent.mcp 公共 API；
- `CHANGELOG.md`：新增条目（additive）；
- `THIRD_PARTY_NOTICES.md`：记录 `mcp` SDK 依赖与版本范围；
- `docs/phases/PHASES.md`：链接本阶段计划与实施记录。

## 8. 风险与未决问题

1. **SDK v1→v2 演进**：transport 接缝已隔离；v2 稳定后单独一次迁移评审，不随 beta 变更；
2. **schema 覆盖不完备**：fallback 透传降低了类型保障 → 以 `fallback_untyped` 元数据显式暴露，观测可见；
3. **只读判定**：无法程序化证明 MCP 工具只读 → 从严按副作用处理；server 端显式声明只读的优化项留待后续；
4. **长任务工具**：后台任务（SEP-1686）与本框架节点超时语义冲突 → 本阶段不接后台任务，magent 超时为硬上限；映射在 Phase 13 硬化阶段评审。

---

## 9. 实施记录

### 9.1 P10.1 骨架（已实施，2026-11）

模块落地于 `src/magent/mcp/`，测试与 `mypy src/magent` 门禁均通过：

| 文件 | 状态 | 内容 |
|------|------|------|
| `errors.py` | ✅ | `KIND_*` 分类常量；`McpToolError` 家族（可重试类同时继承 `RetryableError`，兼容 `ToolTimeoutError`）；`build_tool_error` 工厂 |
| `spec.py` | ✅ | `McpServerConfig`（frozen，factory 注入）、`McpToolDescriptor`、`McpToolEntry`、`McpToolsetSnapshot`（构造期计算 fingerprint） |
| `transport.py` | ✅ | `McpTransport` Protocol + `McpCallOutcome`（SDK 类型不越过接缝） |
| `schema.py` | ✅ | JSON Schema 子集 → pydantic 动态模型；三态：`absent` / `typed` / `untyped` |
| `fake.py` | ✅ | `FakeMcpServer` + `InMemoryMcpTransport` + `FakeTransportFactory`（离线确定性替身，零 SDK 导入） |
| `proxy.py` | ✅ | `McpToolProxy`：副作用策略推导、超时硬上限、事件旁路（started/progress/finished/elicitation_denied）、错误归一化 |
| `loader.py` | ✅ | 两段式 load（plan→register）：显式 allowlist 强制、撞名拒绝、失败即关闭全部 transport、快照指纹 |
| `stdio.py` / `http.py` | ⏳ P10.2 | SDK 占位工厂：懒加载检查 + 明确指向 P10.2 的错误信息 |

实施中的设计修正（以测试证据回写本计划）：

1. **命名空间隔离语义**：`<server>__<tool>` 前缀天然隔离两个 server 的同名工具——两个 server 各自暴露 `echo` 是合法共存而非撞名；同一 qualified name 内的重复（或与既有注册冲突）才中止整个 load；
2. **elicitation 拒绝统一为工具级失败**：adapter 返回 `is_error=True` outcome（kind=`elicitation_denied`）而非抛出，agent 看到统一的 `ToolResult.failure` 形态；无论拒绝发生在哪条路径，`tool.mcp.elicitation_denied` 事件都会发出；
3. **schema 解析增强**：`type` 缺失但含 `properties` 的 schema 仍按对象解析；anyOf/oneOf/allOf/`$ref`/if/not 一律 fallback；
4. **恢复校验留待 10.2**：快照与 fingerprint 已就绪，但 run 启动时落库与 resume 复核需要 executor 侧集成（Phase 10.2 的验收项）。

测试：`tests/unit/test_mcp_{schema,errors,spec,proxy,loader,agent_flow}.py` 共 67 例，关键证据：

- rate-limit 类可重试错误被 `ReliabilityPolicy` 正确重试（`report.retry_count == 2`，共 3 次调用）；
- 同参数 MCP side-effect 工具经 registry 两次调用只执行一次（`sink.write_count == 1`）；
- MCP 工具与本地工具同样被 registry 的 `input_model` 校验拒绝（同一 policy pipeline 的契约证据）；
- load 中止时全部 transport 关闭（无悬挂会话）、注册无部分残留；
- Windows 控制台 mojibake 风险：错误消息只使用 ASCII 分隔符。

### 9.2 P10.2 真实 stdio transport（已实施并实测通过，2026-11）

| 文件 | 状态 | 内容 |
|------|------|------|
| `stdio.py` | ✅ 实装 | `StdioMcpTransport`：官方 SDK（`stdio_client`/`ClientSession`，实测 v1.30.0）驱动本地子进程；`AsyncExitStack` 生命周期（connect 幂等、close 双调用安全、connect 半途失败即回滚栈）；SDK 类型只存活在本模块内部；progress 通知经 SDK 回调（async `(progress, total, message)` 形状）转发进 proxy 的同步 hook |
| `http.py` | ⏳ | 占位不变（streamable HTTP 随后续评审放开） |
| `errors.py` 增量 | ✅ | `map_transport_exception`：`TimeoutError`→`timeout`；SDK `McpError` 按 JSON-RPC code 映射（-32700/-32600/-32601/-32602→`invalid`；-32603 internal 与 -32000 `CONNECTION_CLOSED`→`transient`；其余→`permanent`）；OSError 系→`transient`；未知→`permanent`（"未知失败=不重试"的框架立场） |
| `schema.py` 增量 | ✅ | **`$defs` + 内部 `$ref` 解析**（深度上限防环）与**严格可选 anyOf 模式**（`anyOf: [X, {"type":"null"}]`，即 pydantic `Optional[X]`）转入 typed；真并集/allOf/oneOf/if/not 仍显式 untyped |
| `tools/mcp_example_server.py` | ✅ 新资产 | 真实 FastMCP 服务器（stdio，`readOnlyHint=True` 注解）：`echo` / `profile_query`（真实 enum，经 `Service(str, Enum)` 生成 schema）/ `osv_lookup`（OSV.dev 只读网络读；服务端异常→`isError` 统一回流） |
| `tests/live/test_mcp_stdio_smoke.py` | ✅ 新增 | 真实进程冒烟；`pytest.mark.live` + `MAGENT_RUN_LIVE=1` 双重门控，默认全部 skipped |
| `pyproject.toml` | ✅ | 注册 `live` marker |

真实运行证据（`MAGENT_RUN_LIVE=1 pytest tests/live -q` → **3 passed**，~9s）：

1. **端到端真实化**：真实 spawn → `initialize()` → `list_tools()`（descriptor 含服务器真实 annotations）→ loader 注册（allowlist/冷严策略生效）→ registry invoke，全程无 stub 参与；
2. **真实 schema 的枚举校验打穿**：registry 依据**服务器声明**的 JSON Schema（`$defs/Service` enum，经 `$ref` 间接引用）以 `ToolValidationError` 拒绝非法枚举——MCP 工具与本地工具同一 policy pipeline 的契约实证；
3. **服务端失败形态统一**：服务器内部异常（不存在 ID → OSV 404 → 工具抛错）以 `isError` 结果回流，客户端得到 `res.ok == False, error.kind == "permanent"`，与 P10.1 语义一致；
4. **真实只读网络读**：`osv_lookup("CVE-2024-3094")` 返回 OSV 记录（xz 事件，含 summary），客户端侧零网络代码；网络不可达时 live 测试以 skip 软失败；
5. 离线门禁不受影响：默认 run 下 live 用例 skipped；离线套件 517 passed、mcp 单测 72 passed、`mypy src/magent` 零错误保持。

真实世界发现（均已回写设计与文档）：

1. **FastMCP 把标量返回包进 `structuredContent: {"result": ...}`**（SDK 1.30 结构化输出默认开启）：proxy 保持"structured 优先"透传，`res.output` 是信封对象；LLM 视角的解包策略列入后续评审，不在 transport 层猜测拆包；
2. **pydantic 系服务器生成的 schema 一律 `$defs` + `$ref`**（枚举/嵌套模型无一例外）：P10.1 版转换器把 `$ref` 当 exotic 全量 fallback，会导致真实服务器**静默失去类型保障**——已硬化为解析内部引用，并新增 5 个单测锁定该行为（含真并集仍 untyped、不可解析引用仍 untyped 的守门）；
3. **`CONNECTION_CLOSED = -32000`** 属连接层瞬时错误，必须映射 `transient`，否则一次断连就被判死（与"未知失败不重试"的保守默认不同——这是显式已知的连接语义）；
4. **Windows 控制台 GBK/CP936**：子进程 stderr 译码与控制台输出都可能 mojibake——transport 暴露 `errlog` 参数（live 测试传真实文件句柄），错误消息与日志保持 ASCII。

P10.2 剩余（转入后续候选，见 §10 / §8）：

- [ ] 快照 fingerprint 的 run 级落库与 resume 复核（executor 侧集成）；
- [ ] `tests/contract/mcp/` 契约冻结测试；
- [ ] streamable HTTP transport（待网络策略 L2/L3 边界确认后实装）。

---

## 10. 真实数据源接入评估（Phase 10 后续，未定案）

下游 VulnTell 已登记来源（NVD / OSV / GitHub Advisory 等）对应的 MCP 生态候选，按本仓库纪律（不盲引第三方源码、密钥只走环境变量、server 级显式 allowlist）逐项评估：

| 候选 | 与 VulnTell 关系 | 成本 / 凭据 | 结论 |
|------|------------------|-------------|------|
| 自有 FastMCP 服务器（把 `tools/mcp_example_server.py` 扩展为正式 OSV/NVD 检索服务器） | 直接命中已登记来源；协议字节真实、代码自持 | 零新增依赖；需透传 `VULNTELL_PROXY` 给服务端进程供出网 | **推荐短期路线**：P10.2 冒烟资产的自然升级；可与既有 per-source REST 适配器对照验证（同一端点双实现互检） |
| GitHub 官方 MCP server（github/github-mcp-server） | GitHub Advisory 数据面 | Go 二进制或 Docker + `GITHUB_TOKEN`；第三方二进制须做来源/完整性评审 | **中期候选**：采纳前提 = 供应链评审记录 + token 仅经环境变量注入 + 401/403 映射确认走 `auth`（fail-fast 不重试） |
| 社区 OSV/NVD MCP server | 直接命中来源，但实现质量参差 | 各 server 依赖与行为需逐个审计 | **暂缓**：优先用自有薄服务器封装 OSV；不引入未经审计的第三方源码（与 fixture/来源追溯纪律一致） |
| NVD 官方 MCP server | n/a | 官方未提供（截至 2026-11 生态盘点） | 维持 REST 适配器路线，等待官方生态定型 |

共通风险提示：真实 server 的工具可能触发限流（429 类）→ 依赖 `rate_limited`→`RetryableError` 链路的 backoff 拓扑（P10.1 已有单测全覆盖）；任何 server 的工具注册必须在 `McpServerConfig.allow_tools` 显式声明，默认拒绝信任全部工具。

定案待输入：① 是否接受引入 GitHub 官方二进制（供应链评审结论）；② VulnTell 侧 token 与接口配额预算。两项明确后再立 P10.3 计划。

---

## 11. 实施记录：MCP 通道首个真实下游——VulnTell 每日简报（2026-11-07）

§10 "自有 FastMCP 服务器"路线已从评估变成现实：每日简报工作流把 P10.2 的
stdio transport 真实接进 VulnTell 采集拓扑，并落地了§10 提出的"双实现互检"。

| 组件 | 内容 |
|------|------|
| `apps/vulntell/sources/mcp_adapter.py` | 数据面 `McpSourceAdapter`：直接使用 `magent.mcp` transport 接缝（不经 loader——那是 ToolRegistry 的策略面），实现 CollectAgent 的 `fetch` 协议；OSV 原始 JSON → VulnTell 规范 payload 映射；单 ID 失败只跳过、全失败才整体降级；窗口过滤 + FastMCP `{"result": ...}` 信封兼容 |
| `tools/mcp_example_server.py` 增量 | 新增 `osv_get_payload(vuln_id) -> dict`（raw OSV JSON，structured content）——服务"采集路径"与"双路径对照"双用途；`osv_lookup` 字符串摘要工具保留 |
| `apps/vulntell/pipeline/graph.py` 增量 | `build_daily_vulntell_graph`：既有 2 源定型拓扑推广为 N 源并行扇出（沿用全部 agent 与节点命名约定；既有图零改动，契约冻结不动） |
| `apps/vulntell/sources/mcp_bridge.py` | `DualPathProbe`：同一 OSV 端点 REST 直连 GET vs MCP 工具调用，产出 canonical-hash 一致性 + 归一化字段一致性 + 同形失败统计（失败形态也是证据） |
| `apps/vulntell/reporting/dashboard.py` | 静态单文件 HTML 前端：多智能体执行时间线 / 来源状态 / 每来源指标卡（`compute_source_metrics` 复用）/ 质量告警聚合 / 双路径对照表 / canonical 预览；零外部 URL，内嵌 `<` 转义加固的 JSON 数据帧 |
| `apps/vulntell/pipeline/daily.py` (+ `apps/vulntell/daily.py` 入口) | 日期锚定 run_id（同日重跑幂等）、依赖注入全替身可离线测、live 调度脚本 `scripts/daily_briefing.ps1` |

设计纪律落实情况：

1. **分层不越界**：magent（L1/L2）侧新增为零——数据面直接用 P10 已冻结的
   transport 接缝；领域映射（OSV → payload）全部在 VulnTell（L3）；
2. **离线替身完备**：所有新模块离线测试（`magent.mcp.fake` + stub adapter +
   scripted http stub），`tests/live/test_daily_live_smoke.py` 是唯一真实链路
   冒烟（`MAGENT_RUN_LIVE=1` 门控，default 全量 skipped）；
3. **证明力**（2026-11-07 真实运行）：KEV 50 条真实采集、MCP 路径 ok、
   双路径 2/2 canonical hash 一致（`CVE-2024-3094` / `CVE-2021-44228`），
   且 MCP 路径延迟（~1.3s）低于直连（~2.1s）——Q2 结论"互补而非替代"获得
   量化证据；
4. **意外收获（既有 bug 修复）**：live 揭出 phase-5 CISA KEV 适配器
   `max_records` 抽样截断把 `end_idx` 一起截断，后续批次 `start>end` 恒空
   且 `has_more` 永真 → 翻页死循环；已修正为"抽样即截断"语义并保持既有
   9 例单测全绿（`apps/vulntell/config.py` 重复字段声明一并修复）；
5. **后续边界**（不打本阶段）：策略面接入（把 MCP 服务器工具注册进
   ToolRegistry 让 LLM 走 `tool_calls` 循环选取采集工具）是 Phase 11 事项；
   每日工作流的 MCP 样本 ID 目前由配置注入，KEV→OSV 的" harvested ID 增补"
   可作为后续评估。
