# 阶段 3：并发执行与 EventBus

## 1. 当前状态

阶段 3 的主要功能已经实现并完成发布：fan-out/fan-in、状态 reducer、最大并发限制、失败时的兄弟分支取消和进程内 EventBus。阶段 4 回归后当前工作区共有 103 个离线测试，全部通过。

阶段 3 的能力已被阶段 4 的可靠性 runner 和结构化尝试报告复用；本文件保留阶段 3 的拓扑和并发语义，后续 checkpoint 语义见 [`PHASE5.md`](F:/personal/tool/muti-agent/docs/PHASE5.md)。

## 2. 阶段目标与范围

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

## 3. 并发 Graph 语义

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

## 4. 状态合并

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

## 5. 失败和取消

阶段 3 采用 fail-fast：

- 一个分支失败后，不启动新的相关下游节点。
- 已启动的兄弟分支收到取消信号并完成清理。
- 根因节点记为 `FAILED`。
- 因失败传播而取消的已启动节点记为 `CANCELLED`。
- 未启动的依赖节点记为 `NOT_EXECUTED`。
- 每个节点只有一条最终 `StepRecord`。
- 不进行自动重试和超时处理。

调用方主动取消整个运行与分支失败传播是不同语义，阶段 4 会进一步统一调用方取消和超时策略。

## 6. EventBus

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

## 7. 报告和公共 API

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

## 8. 当前验收结果

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

## 9. 进入阶段 4 的门禁

进入阶段 4 前必须：

- [ ] 提交阶段 3 的未提交代码变更
- [ ] 运行完整测试和包导入 smoke test
- [ ] 确认报告字段和 `docs/API.md` 一致
- [ ] 保留并记录并发基准结果
- [ ] 在 `ROADMAP.md` 中将阶段 3 标记为已完成

阶段 4 的详细方案见 [`PHASE4.md`](F:/personal/tool/muti-agent/docs/PHASE4.md)。
