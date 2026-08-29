# 阶段 4：超时、重试、取消与错误策略（已完成）

## 1. 当前基线

阶段 1～3 已建立以下能力：

- `BaseAgent`、类型化 State、`AgentResult` 和 `Runtime`
- `SequentialExecutor`
- 可校验的 Graph、条件路由和单路径执行
- fan-out/fan-in、显式 reducer 和有界并发
- `FAILED`、`CANCELLED`、`NOT_EXECUTED` 状态
- 进程内 EventBus
- 103 个离线测试通过

阶段 4 已完成阶段 3 发布收尾，确认 `StepRecord`/`ExecutionReport` 向后兼容，并将重试、超时、取消和尝试历史接入顺序/并发执行器。Checkpoint、进程恢复和持久化幂等属于下一阶段，详见 [`PHASE5.md`](docs/PHASE5.md)。

## 2. 阶段目标

为 Agent 调用建立显式、可组合、可测试的可靠性策略：

1. 节点级超时
2. 可重试错误与不可重试错误分类
3. 最大尝试次数和指数退避
4. 调用方取消和取消传播
5. 失败、超时、取消和跳过的统一报告
6. 顺序 Graph、并发 Graph 和 SequentialExecutor 的一致行为

本阶段关注“单次运行如何可靠地完成或明确失败”，不实现 Checkpoint 和进程恢复。

## 3. 关键语义区分

框架必须区分三种情况：

| 情况 | 含义 | 默认处理 |
|------|------|----------|
| Agent 业务失败 | Agent 正常启动，但返回 FAILED 或抛出业务错误 | 按错误分类决定重试或终止 |
| 节点超时 | Agent 在规定时间内没有完成 | 取消当前任务，按策略决定是否重试 |
| 调用方取消 | 用户、上层任务或进程主动取消整个运行 | 立即停止，不重试，向上传播取消 |

阶段 3 中“一个并行分支失败导致兄弟任务取消”属于失败传播；阶段 4 的调用方取消是整个运行的外部生命周期信号。两者必须在报告中可区分。

## 4. 策略对象设计

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

## 5. 重试设计

### 5.1 尝试次数

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

### 5.2 默认不可重试的错误

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

### 5.3 退避算法

建议使用指数退避并设置上限：

```text
delay = min(backoff_max, backoff_base × 2^(attempt - 1)) + jitter
```

生产实现必须避免所有任务在同一时刻同步重试。测试中应注入 sleeper 和随机数生成器，不使用真实长时间 `sleep`。

### 5.4 状态副作用

重试前必须明确 Agent 是否有外部副作用。阶段 4 要求：

- 状态只在一次尝试成功并返回有效结果后合并
- 失败尝试的部分结果不得合并
- 有副作用的 Agent 必须由调用方声明幂等性或使用幂等键
- EventBus 生命周期事件可以记录每次尝试，但不能将失败尝试当作成功结果

## 6. 超时设计

### 6.1 节点级超时

使用 `asyncio.wait_for()` 或 Python 3.11 的等价机制包裹单个 Agent 调用。超时后：

- 当前任务收到取消
- 等待清理完成
- 记录 `TimeoutError` 和实际尝试次数
- 未完成的 AgentResult 不参与状态合并
- 根据 RetryPolicy 决定是否再次尝试

### 6.2 超时范围

阶段 4 首版只实现节点级超时。全局运行超时需要与并发调度、Checkpoint 和恢复结合，暂不作为默认功能。

### 6.3 清理保证

Agent 可能在 `finally` 中释放资源。Executor 必须等待取消后的清理完成，不能留下后台任务。测试需要使用 Event/barrier 验证清理已发生，而不是仅等待固定时间。

## 7. 取消设计

### 7.1 调用方取消

当外层任务取消 `graph.run()` 时：

- 取消信号传播到当前 Agent 和全部并发子任务
- 不进行重试
- 不合并未完成结果
- EventBus 可以发布运行取消事件，但发布失败不能阻止取消清理
- `CancelledError` 应按 asyncio 约定向上传播，或转换为明确的顶层运行状态，但不能静默吞掉

### 7.2 失败传播取消

保留阶段 3 行为：一个分支失败时取消同一 fan-out 中的兄弟任务。报告区分：

- 失败根因节点：`FAILED`
- 因根因被取消的已启动节点：`CANCELLED`
- 因依赖失败而未启动的节点：`NOT_EXECUTED`

每个节点仍只能产生一条最终 `StepRecord`，尝试历史放在该记录的 `attempts` 或独立报告字段中。

## 8. 错误策略

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

## 9. 报告设计

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

## 10. 推荐实现结构

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

## 11. 任务拆分

### Task 0：阶段 3 发布收尾

提交 `core/executor.py` 的报告字段变更；确认 74 个测试、公共导出和文档一致；建立阶段 4 的干净基线。

### Task 1：策略和错误类型

实现策略对象、参数校验、可重试错误协议和默认策略。默认行为必须与现有版本一致。

### Task 2：统一单节点 Runner

实现一次 Agent 调用的超时、异常分类、重试和状态结果返回；注入 clock、sleeper 和 jitter 生成器。

### Task 3：接入 SequentialExecutor

保持阶段 1 的顺序和 fail-fast 语义，增加配置化重试和节点超时；补充报告中的尝试历史。

### Task 4：接入顺序 Graph

让条件路由节点和普通节点使用同一可靠性 Runner，确保路由失败、状态更新失败不会被错误重试。

### Task 5：接入并发 Graph

处理并发分支的节点超时、兄弟取消、调用方取消和任务清理；确保失败尝试与取消尝试不参与 reducer。

### Task 6：报告、EventBus 和文档

发布尝试开始、尝试失败、超时、重试和最终状态事件；更新 `docs/API.md`、README 和 `COMPARISON.md`。

### Task 7：基准与提交

比较无重试、重试成功、超时失败和并发取消场景的耗时与资源；形成阶段 4 独立提交。

## 12. 测试要求

### 策略和重试

- [x] `max_attempts=1` 不发生重试
- [x] 可重试错误按最大次数执行
- [x] 不可重试错误立即终止
- [x] 退避时间遵守上限
- [x] jitter 可注入且测试可重复
- [x] 重试成功后只合并最后一次成功结果
- [x] 所有失败尝试都出现在尝试历史中

### 超时和取消

- [x] 节点超时后任务被取消并完成清理
- [x] 超时不合并未完成结果
- [x] 超时可按策略重试
- [x] 调用方取消不会触发重试
- [x] 调用方取消会传播到所有并发子任务
- [x] 失败传播取消与调用方取消可区分
- [x] 不存在遗留后台任务

### 错误和兼容性

- [x] 状态校验错误不重试
- [x] reducer 冲突不重试
- [x] 路由未知 label 不重试
- [x] `FAILED`、`TIMEOUT`、`CANCELLED`、`NOT_EXECUTED` 可区分
- [x] 每个节点只有一条最终步骤记录
- [x] 阶段 1～3 的原有测试全部通过
- [x] 无策略配置时旧行为不变

### 质量验收

- [x] 阶段 4 新增不少于 20 个有意义的离线测试
- [x] 不使用真实长时间 sleep，使用注入的 sleeper 或同步控制器
- [x] 测试不访问网络、真实数据库或 LLM
- [x] 报告可以 JSON 序列化和反序列化
- [x] 运行日志不泄露敏感信息

## 13. 完成定义

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

## 14. 建议提交

```text
chore(phase3): close release gate
feat(reliability): add retry and timeout policies
feat(reliability): add unified node runner
feat(core): integrate reliability with sequential executor
feat(graph): integrate reliability with graph executors
test(reliability): cover timeout retry and cancellation
docs: document phase-4 reliability semantics
```
