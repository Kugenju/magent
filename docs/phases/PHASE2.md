# 阶段 2：Graph 与顺序、条件执行

## 1. 当前基线

阶段 1 已完成最小执行内核：

- 提交：`70c08e9`
- 测试：17 个测试通过
- 已有能力：`BaseAgent`、Pydantic 状态更新、`AgentResult`、`Runtime`、`SequentialExecutor`、结构化执行报告
- 已验证：Producer/Consumer 离线示例、fail-fast、非法更新检测、重复 Agent 名称检测

阶段 2 应在现有 API 上增量实现，不能通过重写阶段 1 来实现 Graph。`SequentialExecutor` 仍需保持可用。

当前实现状态：Graph 相关代码已经存在于工作区，阶段 1 与阶段 2 测试共 39 个并全部通过，但阶段 2 尚未完成正式验收。进入阶段 3 前必须完成本文件第 3 节的收口项，并形成独立提交。

## 2. 阶段目标

将当前“Agent 列表顺序执行”扩展为“可校验的有向执行图”，支持：

1. 节点注册和唯一节点 ID
2. 无条件边
3. 基于状态的条件路由
4. Graph 编译期校验
5. 图上的单进程顺序执行
6. 与阶段 1 相同的状态更新、错误和执行报告语义

本阶段的核心产出不是并发，而是明确、可测试、可扩展的图拓扑和路由语义。

## 3. 进入条件：先完成阶段 1 工程收口

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

## 4. 范围与非目标

### 本阶段包含

- `GraphBuilder` 或等价的可变构建器
- 编译后的不可变 Graph
- 节点、无条件边、条件边和 `END` 终点
- 顺序 `GraphExecutor`
- Graph 结构校验
- 路由和执行测试

### 本阶段不包含

- 并行执行、fan-out/fan-in
- 循环和自引用边
- EventBus
- 重试、超时和取消策略
- Checkpoint 和持久化
- LLM、工具调用和自主规划
- VulnTell 业务 Agent

并行执行需要状态 reducer 和冲突策略，循环执行需要最大步数、恢复和取消语义，应分别放到后续阶段。

## 5. 推荐的公共 API

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

### API 语义

- `node_id` 是 Graph 内部唯一标识，可以与 `agent.name` 不同
- `add_node()` 只注册节点，不执行 Agent
- `set_entry_point()` 只能设置一个入口
- `add_edge(source, target)` 表示唯一确定的下一节点
- `add_conditional_edges(source, router, mapping)` 由 `router(state)` 返回 label，再通过 mapping 选择目标
- 目标可以是已注册节点或 `END`
- `compile()` 返回不可变的编译结果；编译后不能修改拓扑
- `run()` 使用阶段 1 的 `State`、`AgentResult`、`Runtime` 和 `merge_updates`

阶段 2 的 router 在 Agent 状态更新合并成功后调用，因此可以读取最新状态。router 只能返回合法 label，不得直接修改状态。

## 6. 图执行语义

### 6.1 顺序执行

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

### 6.2 节点出边规则

阶段 2 为保持语义简单，单个节点只能具有以下两种出边形式之一：

- 一条无条件边
- 一组条件边和一个 router

不能同时配置无条件边与条件边，也不能配置多条无条件边。多个后继节点将在阶段 3 并发执行中定义。

### 6.3 终点规则

建议所有正常终点显式指向 `END`。编译器应拒绝没有明确终点的可达路径，避免执行器因“没有下一节点”而产生不一致行为。

### 6.4 失败规则

沿用阶段 1 的 fail-fast：

- Agent 抛出异常：记录结构化 AgentError，停止执行
- Agent 返回 `FAILED`：记录失败结果，停止执行
- 状态更新非法：记录 StateUpdateError，停止执行
- router 抛出异常或返回未知 label：记录路由错误，停止执行
- 不进行自动重试

## 7. 编译期校验

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

## 8. 执行报告设计

优先复用阶段 1 的 `StepRecord` 和 `ExecutionReport`，保持已有调用方兼容：

- `StepRecord.order` 表示实际访问顺序
- `StepRecord.agent_name` 保留 Agent 名称
- 如果需要展示 Graph 节点，新增可选 `node_id` 字段，不删除已有字段
- 报告应能区分已访问节点、失败节点和未访问分支
- 最终状态只包含成功合并的更新

如果新增 `execution_mode`、`graph_name` 等字段，必须提供默认值，不能破坏阶段 1 的报告反序列化。

## 9. 推荐实现结构

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

## 10. 任务拆分

### Task 1：阶段 1 工程收口

修复集合默认值、冲突更新原子性和 Runtime clock 一致性，补充相应回归测试。不得引入 Graph 依赖。

### Task 2：Graph 数据结构

实现节点、边、入口和 `END` 表达。构建器应允许逐步添加拓扑，但不在添加时执行 Agent。

### Task 3：Graph 编译校验

实现节点/边存在性、出边规则、可达性、环检测和终点检测。所有校验错误使用明确异常类型。

### Task 4：无条件图执行

实现 A→B→C→END，复用阶段 1 的状态合并、报告和 fail-fast 行为。

### Task 5：条件路由

实现 router、label mapping、B/C 分支和 END 分支，验证 router 读取的是更新后的状态。

### Task 6：兼容性与文档

确保旧的 `SequentialExecutor` 测试继续通过；更新 `README.md` 或 `../architecture/API.md`，添加最小 Graph 示例和当前限制。

## 11. 测试要求

至少覆盖以下场景：

### 构建和校验

- [ ] 空 Graph 编译失败
- [ ] 未设置入口编译失败
- [ ] 重复节点失败
- [ ] 未知 source/target 失败
- [ ] 节点不可达失败
- [ ] 存在环失败
- [ ] 同时配置无条件边和条件边失败
- [ ] 多条无条件边失败
- [ ] 缺少 `END` 的路径失败

### 执行和路由

- [ ] A→B→C→END 按正确顺序执行
- [ ] 条件为 true 时只执行 B 分支
- [ ] 条件为 false 时只执行 C 或 END 分支
- [ ] router 可以读取前一节点更新后的状态
- [ ] 未选分支不会执行或产生副作用
- [ ] Agent 更新可传递到后续节点
- [ ] Agent 失败后停止后续路径
- [ ] router 失败或返回未知 label 时结构化失败
- [ ] 最终报告包含实际路径和最终状态

### 兼容性和质量

- [ ] 阶段 1 的原有 17 个测试继续通过
- [ ] 阶段 2 新增不少于 12 个有意义的测试
- [ ] 测试不访问网络、数据库或 LLM
- [ ] Graph 编译后修改 Builder 不影响已编译 Graph
- [ ] `import magent` 和离线示例继续成功

## 12. 完成定义

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

## 13. 建议提交

```text
fix(core): close phase-1 execution semantics
feat(graph): add graph builder and compiled topology
feat(graph): add graph validation
feat(graph): add sequential graph executor
feat(graph): add conditional routing
test(graph): cover validation and execution paths
docs: document phase-2 graph API
```
