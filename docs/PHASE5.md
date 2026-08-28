# 阶段 5：Checkpoint、恢复与幂等（功能完成，待发布门禁）

## 1. 当前基线

阶段 1～5 的功能实现已完成，当前全量回归为 `125 passed`；阶段 5 改动仍在工作区，尚未形成独立发布提交。
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

阶段 5 的首要任务已经完成，下一步是关闭本文件第 12 节的发布门禁，而不是继续扩展 LLM、工具或 VulnTell 业务；
`checkpoint_store=None` 时执行器行为与阶段 1～4 完全一致。

当前结论：阶段 5 可以进入发布收尾，但在以下问题被测试和代码确认前，不能宣称具备生产级恢复保证：

- 从 SQLite 读取 checkpoint 时必须重新校验 checksum，而不能只信任数据库中的 checksum 字段；
- 并发 Graph 写入 checkpoint 时必须有进程内序列分配机制，不能让多个任务竞争同一个序号；
- `SideEffectSink` 的“查询后执行再记录”存在同一 execution key 的并发竞态，需要原子 claim 或明确的处理中状态；
- 非字典副作用结果的首次返回值与重放返回值必须保持同一结构；
- `RunRecord.status`、失败/取消/中断边界和 `NODE_STARTED` 的真实 attempt 信息必须与报告和恢复逻辑一致；
- 失败、损坏、取消和存储异常路径必须保证资源关闭，并明确哪些状态已经持久化。

## 2. 阶段目标

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

## 3. 范围与非目标

### 3.1 本阶段包含

- `CheckpointStore` 抽象和 SQLite 本地实现；
- 运行元数据、状态快照、节点边界、尝试历史和恢复游标；
- `SequentialExecutor` 与 `GraphExecutor` 的 checkpoint 接入；
- 显式 `resume` API，默认不自动恢复；
- 稳定的节点版本、工作流/图版本和状态 schema 指纹；
- 执行键（idempotency key）生成协议及框架内的幂等记录；
- 破坏恢复条件时的结构化错误和诊断信息；
- 至少 20 个离线单元/集成测试和一个可重复的中断恢复示例。

### 3.2 本阶段不包含

- 多进程、多机或分布式 checkpoint 协议；
- 主从切换、租约、领导者选举和消息队列；
- 跨数据库、外部 API 与 checkpoint 的分布式事务；
- 任意 Python 对象的 pickle 持久化；
- 自动迁移旧状态 schema；
- 循环图、动态规划、LLM、工具注册或 VulnTell 业务实现；
- 加密密钥管理和云端对象存储适配器。

### 3.3 阶段风险与注意事项

- Checkpoint 写入与进程崩溃之间始终存在窗口；“外部副作用已发生、成功记录尚未提交”必须按未知结果设计，不能靠状态快照猜测。
- 取消信号可能到达状态合并或 SQLite 提交附近。提交必须有清晰的原子边界，并通过故障注入测试验证不会出现“报告成功但没有持久化状态”。
- Agent、router 和 reducer 的非确定性会破坏恢复一致性。已选择的路由必须持久化；影响状态的 reducer 必须保持确定性，不能依赖完成顺序、当前时间或随机数。
- 节点 ID、节点 version 和 workflow version 不是展示字段，而是恢复安全条件。行为、提示词、工具协议或输出 schema 改变时必须升级版本。
- 全量 JSON 快照简单可靠但可能放大磁盘和写入开销。阶段 5 先保证语义，压缩、增量快照和归档留到后续，不得为优化跳过成功边界。
- SQLite 是单机单写者存储。需要设置明确的锁/忙等待和事务超时；不能通过无限重试掩盖数据库损坏或资源泄漏。
- 状态可能包含凭据、漏洞原文或个人数据。默认不写入密钥和敏感日志；阶段 5 不提供加密时，应在文档中要求安全文件权限和调用方脱敏。
- 恢复调度必须防止重复创建同一个逻辑节点的任务。frontier、已提交集合和 execution key 要共同参与去重，不能只依赖内存 `tasks`。

## 4. 必须先冻结的恢复语义

### 4.1 Checkpoint 是提交记录，不是日志缓存

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

### 4.2 节点状态边界

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

### 4.3 顺序 Graph 恢复

顺序执行器保存：初始状态、已提交节点顺序、最后成功状态和下一个节点索引。恢复时：

- 已有成功提交的节点不得再次调用 Agent；
- 最近一个未提交或 `RUNNING` 节点从其 `input_state` 重新调用；
- `RUNNING` 记录对应的未完成尝试应标记为 `ABANDONED`（只在 checkpoint 历史中使用）；
- 阶段 4 的 `max_attempts` 默认包含已经持久化的尝试和恢复后新增的尝试；
- 已提交状态与调用方传入的初始状态不一致时拒绝恢复，不静默覆盖。

### 4.4 并发 Graph 恢复

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

## 5. 存储抽象与 SQLite 方案

### 5.1 `CheckpointStore` 最小契约

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

### 5.2 建议的 SQLite 表

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

## 6. 版本、校验和恢复兼容性

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

## 7. 幂等设计与已知边界

### 7.1 执行键

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

### 7.2 能保证什么

- 框架内的状态 checkpoint 提交：在 SQLite 事务成功后视为一次提交，重复提交同一记录不会
  产生第二份逻辑结果；
- 通过 `effects` 或业务数据库唯一键保护的写入：相同执行键可安全重试；
- 不受框架控制的外部 API、消息发送和文件写入：最多只能保证 at-least-once，不能由
  checkpoint 单独推出 exactly-once。

因此下游 Agent 必须将“调用外部副作用”和“返回状态更新”分开设计，并声明副作用是否可重试。
阶段 5 的测试应使用一个可控的 fake side-effect sink，模拟“副作用已发生但进程在 checkpoint
前崩溃”的窗口，验证相同 execution key 不重复写入。

## 8. 与阶段 4 的衔接

- `run_id` 沿用现有执行报告中的值，恢复不能生成新的 run ID；
- `AttemptRecord` 增加持久化边界所需的序列/状态信息时保持旧字段兼容；
- 超时、重试和取消仍由 `run_node` 统一处理，Checkpoint 不复制一套重试逻辑；
- 退避等待期间进程中断时，恢复应依据已记录的尝试次数决定是否还允许重试；
- 调用方取消只提交 `RUN_CANCELLED` 和已完成节点，不能把取消中的节点标为成功；
- 失败传播取消的兄弟分支保持 `CANCELLED`/`NOT_EXECUTED` 区分，只有成功提交的分支进入 join；
- EventBus 仍是旁路通知。事件丢失不能改变 checkpoint，也不能把事件当作恢复依据。

## 9. 推荐任务拆分

### Task 0：冻结协议和基线

整理 `RunRecord`、`CheckpointRecord`、`EffectRecord`、checkpoint phase 和兼容性错误的字段；
确认现有 103 个测试全部通过，补充一份状态快照 JSON fixture。不得在此任务中接入 SQLite。

### Task 1：Checkpoint 领域模型与抽象

实现不可变/只读的记录模型、序列化/反序列化、canonical JSON、checksum 和
`CheckpointStore` 契约。覆盖缺字段、未知 phase、非法序号和校验失败。

### Task 2：SQLite Store

实现数据库初始化、事务追加、最新记录读取、重复提交、并发读写、关闭和损坏处理。所有 SQL
使用参数绑定；测试使用 `tmp_path`，不依赖固定本地路径。

### Task 3：顺序执行器接入

增加 checkpoint 配置和显式 `resume` 入口；在节点前写入输入快照，在成功合并后原子提交结果与
frontier。验证进程中断后不重新调用已提交节点。

### Task 4：统一恢复控制器

抽取恢复游标、版本检查、`RUNNING → ABANDONED` 处理和报告重建逻辑。恢复应复用现有
`run_node`，不能在 Executor 中复制重试/超时实现。

### Task 5：并发 Graph 接入

持久化分支输入、分支 updates、路由激活信息和 join 父节点提交集合；验证 reducer 顺序、
分支隔离和部分分支恢复。先支持已有无环 DAG，不为恢复引入循环或动态节点。

### Task 6：幂等记录与副作用测试夹具

实现 execution key、effect record 和一个 fake sink 适配器；明确“已记录结果”“处理中”“结果
未知”三种状态的处理。不得把任意真实外部服务接入测试。

### Task 7：报告、文档与示例

让 `ExecutionReport` 能说明是否恢复、恢复自哪个 checkpoint、跳过了哪些已提交节点、发生了
多少 abandoned/replayed attempts；更新 `docs/API.md`、`docs/DESIGN.md` 和 README，并提供
离线中断恢复示例。

### Task 8：回归与阶段发布

运行全量离线测试、序列化兼容测试和资源清理检查；记录 SQLite 版本、Python 版本和测试数量，
形成阶段 5 独立提交。

## 10. 测试要求

至少新增 20 个有意义的离线测试，建议覆盖：

### Store 与数据完整性

- [ ] 新建 run、追加 checkpoint、读取最新 checkpoint；
- [ ] 相同序号和相同内容重复提交不重复产生逻辑记录；
- [ ] 相同序号但内容不同显式报冲突；
- [ ] checksum 错误、JSON 损坏、序号倒退和缺失 run 被拒绝；
- [ ] 状态 schema 不匹配、checkpoint version 不兼容被拒绝；
- [ ] SQLite 事务失败后没有半条成功 checkpoint；
- [ ] 多个 store 操作关闭后不会泄漏连接或后台任务。

### 顺序恢复

- [ ] 第一个节点成功提交后中断，恢复时只执行后续节点；
- [ ] 节点执行中断，恢复从该节点 input snapshot 重跑；
- [ ] 已提交节点不会因重复调用 `resume` 再执行；
- [ ] 恢复保持原 `run_id`，并合并正确的最终 state；
- [ ] 恢复后 attempt 编号连续，abandoned attempt 可追溯；
- [ ] 恢复与阶段 4 重试、超时、取消组合时不重复合并失败结果。

### 并发恢复与幂等

- [ ] 一个分支成功、另一个分支中断时，只恢复未提交分支；
- [ ] join 等待全部成功父节点，不能消费取消或未执行分支；
- [ ] reducer 使用声明顺序，和原始完整运行结果一致；
- [ ] 条件路由结果从 checkpoint 恢复，不再次调用 router；
- [ ] 副作用已发生但提交前中断时，相同 execution key 不重复写入；
- [ ] 不同 run、node、version 或 input 的 key 不发生错误碰撞；
- [ ] 重复 resume、重复完成提交和重复 effect 请求结果稳定。

### 兼容与质量门禁

- [ ] 阶段 1～4 全部原有测试继续通过；
- [ ] 无 `checkpoint_store` 时行为和性能不改变；
- [ ] 所有状态仅经过 Pydantic schema 校验，禁止 pickle；
- [ ] checkpoint 和 report 可 JSON 序列化/反序列化；
- [ ] 测试不访问网络、真实 LLM 或真实外部副作用系统；
- [ ] 运行结束、异常和取消路径均关闭 SQLite 资源。

## 11. 量化验收标准（功能实现）

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

## 12. 当前发布门禁

阶段 5 的核心功能和测试已经完成，但当前工作区仍有未提交改动。正式进入阶段 6 前必须完成
以下收尾动作：

- [ ] 为 SQLite 读取路径增加 checksum 重算和校验测试；
- [ ] 为并发 Graph 增加 checkpoint 序号分配、重复序号和恢复测试；
- [ ] 为 `SideEffectSink` 增加同一 execution key 的并发 claim/处理中测试；
- [ ] 统一副作用首次返回与重放返回的结果结构；
- [ ] 更新并持久化 `RunRecord.status`，覆盖 completed/failed/cancelled/abandoned；
- [ ] 验证所有 checkpoint store、SQLite 连接和取消/异常路径的资源关闭；
- [ ] 更新 README、API、ROADMAP 和本文件的状态描述；
- [ ] 在干净环境运行全量测试、类型检查、离线示例和 `import magent`；
- [ ] 形成阶段 5 实现提交和发布文档提交，并记录测试数量与环境。

在以上门禁未全部通过前，阶段 5 的状态为“功能完成，待发布”，阶段 6 不得接入工具副作用或
LLM 缓存恢复。

## 13. 完成定义

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

## 14. 建议提交节奏

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
