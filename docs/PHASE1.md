# 阶段 1：Agent、State 与 Result 最小执行模型

## 1. 阶段目标

实现自研多智能体框架的第一个稳定内核，回答三个问题：

1. Agent 如何被统一描述和调用？
2. Agent 如何读取状态并返回状态更新？
3. 框架如何在一次运行中按确定顺序执行多个 Agent，并记录结果？

本阶段的目标是稳定公共 API 和执行语义，不追求功能数量。实现应保持本地单进程、异步兼容、确定性和可测试。

## 2. 明确不做的内容

本阶段禁止提前加入以下功能：

- 有向 Graph、条件路由和循环
- 并行执行和 EventBus
- SQLite Checkpoint、进程恢复和分布式执行
- 真实 NVD/CNVD 请求
- LLM、Prompt、工具调用
- VulnTell 数据模型和业务数据库
- 复杂插件发现机制

这些功能会在后续阶段基于本阶段 API 增加。不要为了“未来可能使用”提前设计大量抽象。

## 3. 建议实现范围

### 3.1 包结构

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

### 3.2 Agent 协议

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

### 3.3 State 与 StateUpdate

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

### 3.4 AgentResult

建议至少包含：

```text
status: success | skipped | failed
updates: 状态部分更新
message: 可选说明
error: 可选结构化错误
metadata: 执行元数据
```

阶段 1 的 Agent 异常可以由执行器统一捕获并转换为失败结果，但必须保留原始异常类型、Agent 名称和运行 ID。是否自动重试留到阶段 4，不要在本阶段隐式重试。

### 3.5 Runtime

阶段 1 只实现不可变或只读运行上下文：

- `run_id`
- 当前 Agent 名称
- 开始时间
- 日志接口或最小 logger

`run_id` 应由框架生成，也允许测试传入固定值。不要在 Runtime 中提前塞入重试、Checkpoint、工具和 LLM 配置，除非它们已有明确行为。

### 3.6 顺序执行器

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

## 4. 实现注意事项

### API 与边界

- 统一使用 `async def`，执行器通过 `await agent.run(...)` 调用
- 框架核心不得导入漏洞模型、httpx、数据库驱动或 LLM SDK
- 不要让 Agent 直接持有执行器内部可变状态
- 不要把日志文本当作 Agent 之间的数据协议
- 不要用 `print()` 作为框架核心的观测机制
- 公共对象应提供类型标注和简短 docstring

### 状态安全

- 状态字段应可序列化，为阶段 5 的快照做准备
- Pydantic 模型的可变列表和字典使用 `default_factory`
- 明确更新是浅合并还是字段级替换
- 阶段 1 遇到同一字段重复更新时应采用明确策略：拒绝或后写覆盖；必须写测试
- 不要默认进行深度智能合并

### 错误处理

- 区分 Agent 业务失败和框架执行失败
- 错误信息不能泄漏 API Key 或完整敏感输入
- 不自动吞异常，也不使用裸 `except:`
- 失败报告要能区分“未执行”和“执行失败”
- 不实现隐式重试，避免后续无法统计真实执行次数

### 测试隔离

- 阶段 1 测试不能访问网络、文件系统或真实数据库
- 使用 Dummy Agent 和固定状态验证执行语义
- 测试异步 Agent、同步错误、非法状态更新和重复 Agent 名称
- 时间测试不要依赖精确墙钟值；使用可注入 clock 或只断言耗时非负

## 5. 推荐任务拆分

### Task 1：定义公共类型

实现 Agent、State 约定、AgentResult、ExecutionStatus、Runtime 和框架异常。补充 API docstring 和类型检查。

### Task 2：实现状态校验与更新合并

支持用户定义 Pydantic State，验证部分更新、未知字段、类型错误和重复字段策略。

### Task 3：实现顺序执行器

支持按列表执行 Agent、生成 `run_id`、收集执行报告和默认 fail-fast。

### Task 4：编写单元测试

覆盖成功链路、Agent 异常、failed 结果、非法更新、重复名称、空列表和执行报告。

### Task 5：编写最小示例

实现 `ProducerAgent` 和 `ConsumerAgent`：Producer 将固定值写入状态，Consumer 读取并生成确认信息。示例必须完全离线、可重复运行。

### Task 6：整理文档与提交

补充 README 的最小使用示例、API 说明和阶段记录，提交信息建议为 `feat(core): add minimal agent state executor`。

## 6. 验收标准

### 功能验收

- [ ] 能定义至少两个不依赖业务的 Dummy Agent
- [ ] 执行器按注册顺序调用 Agent
- [ ] 前一个 Agent 的状态更新可被后一个 Agent 读取
- [ ] 最终结果包含最终 State 和 ExecutionReport
- [ ] 空 Agent 列表有明确且有测试覆盖的行为
- [ ] Agent 名称重复时在执行前报错

### 错误验收

- [ ] Agent 抛出异常时，执行器返回或抛出统一框架错误
- [ ] 失败 Agent 后续节点不会执行
- [ ] 报告区分成功、失败和未执行
- [ ] 非法状态字段或类型更新不能静默通过
- [ ] 阶段 1 不发生自动重试

### 质量验收

- [ ] `python -m pytest` 全部通过
- [ ] 测试不访问网络和真实外部服务
- [ ] `import magent` 成功
- [ ] 核心代码有类型标注和必要 docstring
- [ ] 核心依赖不包含业务层依赖
- [ ] README 能让新用户在几分钟内运行 Producer/Consumer 示例

## 7. 阶段完成后的输出

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
