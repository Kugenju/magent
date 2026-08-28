# 阶段 3：并发执行与 EventBus

## 1. 当前基线

工作区当前状态：

- 阶段 1 核心已实现并有回归测�?- 阶段 2 Graph、条件路由和编译校验已实�?- 当前测试总数�?39 个，全部通过
- 阶段 2 代码和文档尚未形成正式提�?
阶段 3 不能以“测试通过”作为唯一前提。必须先完成 [`PHASE2.md`](F:/personal/tool/muti-agent/docs/PHASE2.md) 中的收口项，尤其是：

- CompiledGraph 对外暴露的拓扑结构不能被调用方直接修�?- 条件分支�?router 失败不能产生重复的最终步骤记�?- `GraphExecutor` 的公共导出和 API 文档必须一�?- 阶段 1 的集合默认值、冲突更新原子性和 clock 一致性必须完成确�?
## 2. 阶段目标

在已经支持单路径顺序执行�?Graph 上增加：

1. 无依赖节点的并发执行
2. fan-out / fan-in 的拓扑语�?3. 并行分支的状态隔离和结果合并
4. 最大并发数限制
5. 基于 asyncio 的进程内 EventBus
6. 并发运行的结构化执行报告

本阶段的核心问题是：多个 Agent 同时运行时，状态、错误、消息和生命周期如何保持确定性�?
## 3. 非目�?
本阶段不实现�?
- 自动重试和指数退�?- 节点超时策略
- Checkpoint、进程恢复和持久化消�?- 分布式执行或跨进�?EventBus
- LLM、工具调用和 VulnTell 业务
- 循环图和动态自主规�?
重试、超时和取消策略在阶�?4 统一设计。阶�?3 只实现因并发任务失败而产生的基本 fail-fast 取消传播�?
## 4. 并发 Graph 语义

### 4.1 基本流程

```text
        ┌→ B ─�?A ──────�?    ├→ D
        └→ C ─�?```

执行规则�?
1. A 成功后生成一个稳定的状态快�?2. B �?C 从同一个快照启动，彼此不能直接修改对方状�?3. B、C 分别返回 `AgentResult`
4. 到达 D 前由框架合并分支更新
5. 合并成功�?D 才能执行

状态不能作为多个并�?Agent 之间的可变共享对象。每个分支只能通过结构化结果提交更新�?
### 4.2 Graph API 变化

阶段 2 的单条无条件边规则需要扩展，但要保持�?API 兼容。建议新增显�?API�?
```python
graph.add_parallel_edges("a", ["b", "c"])
graph.add_join("d", parents=["b", "c"])
```

也可以选择�?`add_edge()` 支持多目标，但必须在 `docs/API.md` 中明确：

- 单目标边表示顺序执行
- 多目标边表示 fan-out
- 条件边仍然只选择一个目�?- 同一节点不能混用无条�?fan-out 和条件路�?
推荐优先使用显式 `add_parallel_edges()`，因为它不会改变阶段 2 �?`add_edge()` 的含义�?
### 4.3 就绪条件

节点只有在所有必需前驱完成并成功合并后才进�?ready 状态。阶�?3 不支持“任意一个前驱完成即可执行”的竞速语义�?
编译器需要检查：

- join 节点声明的前驱存�?- 每个并行分支都能到达 join
- 一个节点不会被重复触发
- 图中不包含环
- fan-out 的目标不会形成隐式重复路�?
### 4.4 并发限制

Executor 接受 `max_concurrency`�?
```python
executor = GraphExecutor(compiled, max_concurrency=4)
```

要求�?
- 非法值在构造或编译时拒�?- 不限制时使用明确的默认值，而不是无限创建任�?- 通过 Semaphore 或等价机制限制正在运行的 Agent 数量
- 任务结束后一定释放并发槽�?- 报告记录峰值并发数

## 5. 状态合并设�?
### 5.1 默认策略

并行分支的状态更新不能默认采用“最后写入覆盖”，因为完成顺序不稳定。建议默认：

- 不同字段更新：自动合�?- 同一字段被多个分支更新：抛出 `StateMergeConflictError`
- 需要聚合的字段：显式注�?reducer

示例�?
```text
B 更新 findings=[b]
C 更新 findings=[c]
�?只有�?findings 注册 append reducer 后才合并�?[b, c]
```

### 5.2 Reducer 要求

每个 reducer 必须�?
- �?State 字段显式配置
- 具有确定�?- 尽量满足结合性，方便未来扩展并行合并
- 在测试中覆盖空值、重复值和冲突�?- 不依�?Agent 完成的实际时间顺�?
阶段 3 不实现通用深度合并，不自动猜测列表、字典或对象的合并方式�?
### 5.3 合并顺序

对于需要顺序的 reducer，使用图中声明的边顺序或稳定的节�?ID 顺序，不能使�?asyncio 完成顺序。合并策略和顺序必须出现在执行报告或调试 trace 中�?
## 6. 失败与生命周期语�?
阶段 3 延续 fail-fast，但要定义并发场景：

- 一个分支失败：停止启动尚未开始的相关节点
- 已运行的兄弟分支收到取消信号
- Executor 等待已启动任务完成清�?- 失败节点记录 `FAILED`
- 已启动但被取消的节点需要记�?`CANCELLED`；如果暂不增加状态枚举，必须记录为明确的结构化执行错误，不能伪装成成�?- 未启动节点记�?`NOT_EXECUTED`
- 不自动重�?
建议新增 `CANCELLED` 状态，并保持已有枚举值不变，以便报告区分失败、取消和未执行�?
不能吞掉 `asyncio.CancelledError`，也不能在取消后继续合并被取消分支的部分结果，除非未来明确引�?partial-result 策略�?
## 7. EventBus 设计

### 7.1 定位

EventBus 是进程内、可插拔的旁路通信机制。Graph 的状态流转仍�?Executor 管理，不能要�?Agent 通过 EventBus 才能传递核心结果�?
### 7.2 最小事件模�?
事件至少包含�?
```text
event_id
topic
run_id
source
created_at
payload
```

payload 应支持结构化对象，不能只传未经约束的日志字符串�?
### 7.3 交付语义

阶段 3 采用以下明确限制�?
- 仅内存存�?- 进程�?at-most-once
- 同一订阅者按发布顺序处理事件
- 不保证进程崩溃后的消息恢�?- 不提供持久化重试和消费位�?- `publish()` 的异常行为必须可配置或有明确默认�?
推荐 API�?
```python
subscription = bus.subscribe("agent.completed", handler)
await bus.publish(event)
subscription.unsubscribe()
await bus.close()
```

订阅处理器异常不能静默吞掉。默认可以记录结构化 `EventHandlerError` 并继续通知其他订阅者；如果事件被标记为关键事件，则允许配置为使发布操作失败。该策略必须通过测试固定下来�?
## 8. 推荐实现结构

```text
src/magent/
├── graph/
�?  ├── builder.py          # 扩展 fan-out / join 拓扑
�?  ├── model.py
�?  ├── validator.py
�?  └── executor.py         # ready queue、并发任务和 join
├── events/
�?  ├── model.py            # Event、Subscription
�?  └── bus.py              # In-memory EventBus
└── core/
    ├── result.py           # 兼容并发状�?取消状�?    └── errors.py           # 状态合并和事件错误
tests/unit/
├── test_parallel_graph.py
├── test_state_reducer.py
├── test_event_bus.py
└── test_concurrency_report.py
```

如果不新�?`events/` 包，也可以放�?`core/events.py`，但 Event 模型、订阅生命周期和 Graph 执行逻辑必须分离�?
## 9. 任务拆分

### Task 0：阶�?2 收口

完成阶段 2 所有阻塞问题和回归测试，形成独立提交。收口前不得修改并发语义�?
### Task 1：扩�?Graph 拓扑

确定并实�?fan-out、join 和多前驱模型；补充编译期拓扑校验，并保持单路�?Graph 行为不变�?
### Task 2：实现并发调度器

实现 ready queue、任务启动、完成通知、join 等待�?`max_concurrency`。先使用确定�?Dummy Agent，不接网络�?
### Task 3：实现分支状态隔离和 reducer

让每个分支从同一快照开始，收集 `AgentResult`，在 join 处执行显�?reducer。补充字段冲突测试�?
### Task 4：实现并发失败处�?
实现 fail-fast、兄弟任务取消、清理、FAILED/CANCELLED/NOT_EXECUTED 报告和无隐式重试�?
### Task 5：实�?EventBus

实现事件模型、订�?取消订阅、发布顺序、处理器异常策略�?close 生命周期。EventBus 不参与核心状态合并�?
### Task 6：执行报告和基准

增加峰值并发、节点等待时间、分支合并信息和事件统计；以同一�?Dummy Graph 对比串行和并发执行�?
### Task 7：文档与提交

更新 `docs/API.md`、README �?`COMPARISON.md`，记录并发语义、状�?reducer、EventBus 限制和参考项目对比�?
## 10. 测试要求

### 并发 Graph

- [x] 两个无依�?Agent 实际重叠运行
- [x] `max_concurrency=1` 等价于串行行�?- [x] 并发限制不会超过配置�?- [x] fan-out 后所有分支都执行一�?- [x] join 等待所有必需分支
- [x] 分支只能读取起始快照，不会看到兄弟分支的中间状�?- [x] 不同字段更新可以合并
- [x] 同字段冲突在没有 reducer 时失�?- [x] reducer 结果�?Agent 完成顺序无关
- [x] 编译后修�?Builder 不影响已编译 Graph

### 失败和报�?
- [x] 一个分支失败后不启动新的下游节�?- [x] 已启动兄弟任务被取消并完成清�?- [x] FAILED、CANCELLED、NOT_EXECUTED 可区�?- [x] 被取消任务的结果不参与合�?- [x] 报告中每个节点只有一条最终记�?- [x] 报告包含实际路径、等待时间和峰值并发数
- [x] 阶段 1 和阶�?2 的已有测试全部通过

### EventBus

- [x] 一�?topic 可以有多个订阅�?- [x] 同一订阅者按发布顺序收到事件
- [x] 取消订阅后不再收到事�?- [x] 订阅者异常不会静默消�?- [x] 关闭后不能继续发布或订阅
- [x] EventBus 不会修改 Graph 状�?
### 质量验收

- [x] 阶段 3 新增不少�?18 个有意义的测�?- [x] 所有测试不访问网络、真实数据库�?LLM
- [x] 使用同步事件�?barrier 测试并发，不依赖脆弱�?sleep 计时
- [x] 串行与并发基准可重复运行

## 11. 完成定义

```text
阶段 2 收口并提�?        �?fan-out / join 拓扑语义明确
        �?分支隔离、reducer 和冲突策略明�?        �?并发限制�?fail-fast 生命周期可测�?        �?EventBus 交付语义和异常策略明�?        �?报告无重复、可解释、可重放
        �?阶段 1/2 无回归且完成基准
```

完成后才进入阶段 4 的超时、重试、取消策略和更完整的可靠性设计�?
## 12. 建议提交

```text
fix(phase2): close graph immutability and report semantics
feat(graph): add fan-out and join topology
feat(graph): add bounded concurrent executor
feat(graph): add reducer-based state merge
feat(graph): add concurrent failure lifecycle
feat(events): add in-memory event bus
test: cover concurrency and event delivery
docs: document phase-3 semantics
```
