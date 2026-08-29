# 阶段 8：评测、可观测性与对比实验实施计划

> **交付对象：** 下游开发 Agent。本文是阶段 8 的实施约束、任务拆分和验收标准。
> 阶段 8 只在现有执行语义之上增加观测与实验能力；任何改变调度、状态合并、重试、取消、
> Checkpoint 或 VulnTell 确定性指标含义的改动，都必须另立设计并暂停本阶段。

## 1. 当前基线

阶段 1～7 已完成，最近阶段 7 提交为 `80d7156 docs: document phase-7 VulnTell vertical example`。
当前基线如下：

- `magent` 已支持 Agent、类型化 State、顺序/DAG Graph、fan-out/fan-in、reducer 和并发限制；
- 已支持超时、重试、取消、错误策略、EventBus、SQLite Checkpoint、恢复和稳定幂等键；
- 已支持 Tool Registry、可插拔 LLM Provider、离线 FakeProvider 和 Middleware；
- `examples/vulntell` 已完成离线纵向流程：多源 fixture 采集→标准化→质量告警→去重→持久化→
  可恢复并发 Graph→指标→JSON/Markdown 报告；
- 当前全量测试为 **211 passed**，默认测试不依赖网络、API Key 或真实 LLM；
- 阶段 7 已冻结数据集、时间窗口、解析器版本、去重版本和指标版本，本阶段不得私自替换。

当前缺口是统一 trace/span/run metadata、实验配置与结果 schema、串行/并行 benchmark、恢复和
失败路径的统一观测、VulnTell 质量评测，以及可审计的参考框架对比记录。

## 2. 阶段目标

1. 建立可选、脱敏、有界的 Trace/Span/RunSummary 观测契约；
2. 记录节点等待、执行、attempt、重试、超时、取消、失败、Checkpoint 和恢复信息；
3. 建立固定配置驱动、离线可重复、原始结果可重放的实验运行方式；
4. 以串行执行作为基线，测量并行度、吞吐量、失败恢复和 Checkpoint 开销；
5. 评估 VulnTell 标准化、去重、指标和报告质量，不把小样本事实夸大为普遍结论；
6. 在等价场景下记录 LangGraph、AutoGen、CrewAI 等参考项目的版本、配置和结果，为设计讨论
   提供材料，不把它们变成 `magent` 运行时依赖。

## 3. 非目标

- 不引入分布式调度、远程 tracing 服务、消息队列或生产级监控平台；
- 不修改既有执行语义，不以 benchmark 为理由改变默认重试、并发、超时或指标定义；
- 不默认联网、不调用真实 LLM、不抓取漏洞引用 URL、不使用未授权真实漏洞数据；
- 不实现自动框架排名、统计显著性结论或“通用性能领先”宣传；
- 不把论文历史数据直接当作当前系统观测结果；
- 不将 LangGraph/AutoGen/CrewAI 的内部对象或源码复制到本仓库。

## 4. 观测设计

### 4.1 数据模型

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

### 4.2 采集边界

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

## 5. 实验协议

### 5.1 冻结配置

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

### 5.2 场景矩阵

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

### 5.3 公平对比原则

参考框架对比必须明确记录：精确版本或 commit、Python/依赖版本、运行环境、图结构、输入数据、
并发度、重试/超时配置、预热和计时范围、是否包含序列化/初始化成本。无法建立等价条件时，输出
`not_comparable` 和差异说明，不输出排名。参考框架不可用、版本冲突或网络不可用时，不阻塞
`magent` 本地 benchmark；但报告必须记录缺失项。

## 6. 实施任务拆分

### Task 0：冻结实验协议与目录

- 确认上述字段、状态枚举、时间单位、统计方法和样本门槛；
- 设计 `benchmarks/`、结果输出目录和忽略规则，禁止提交临时数据库、缓存和密钥；
- 记录阶段 7 dataset/window/parser/dedup/metric 版本；
- 产出：本文件补充的 schema 变更记录或独立 `benchmarks/README.md`。

### Task 1：Trace/Span/RunSummary 模型

- 实现 Pydantic/不可变数据模型、校验、JSONL/JSON 序列化和脱敏/大小限制；
- 明确父子关系、attempt 关联、恢复字段和未采集资源字段；
- 不把具体存储后端、OpenTelemetry SDK 或云服务设为核心依赖。

### Task 2：接入现有执行生命周期

- 通过 EventBus、ExecutionReport 和 Checkpoint history 生成统一记录；
- 覆盖顺序图、并行 DAG、失败、重试、超时、取消、恢复和幂等重放；
- 验证观测启用/关闭时最终 State、报告成功性和业务副作用一致。

### Task 3：实验 runner 与串行基线

- 实现固定配置加载、环境快照、seed、重复运行和原始结果保存；
- 建立 VulnTell 的顺序执行基线，并定义计时起止点和正确性断言；
- 提供离线 CLI 或等价入口，默认不写入仓库内固定数据库。

### Task 4：并行与可靠性 benchmark

- 运行至少 3 种并发度，记录吞吐量、峰值并发、等待/执行耗时和结果一致性；
- 运行失败重试、超时、取消和 checkpoint 恢复场景；
- 分离冷启动、框架初始化、业务执行和报告聚合耗时，避免混为一个数字。

### Task 5：VulnTell 业务质量评测

- 使用阶段 7 冻结 fixture；如增加人工标注真值，必须另设标注版本和覆盖说明；
- 评估标准化字段缺失/无效率、跨源一致性、去重 precision/recall/F1（仅在有真值时）、
  报告字段完整性、部分失败可用性和指标重复性；
- 样本不足输出 `insufficient_data`，不得计算无依据排名。

### Task 6：参考框架对比记录

- 先完成设计/API/语义对比，再决定哪些参考框架可运行；
- 为每个框架建立隔离 adapter 或实验脚本，禁止污染 `src/magent` 依赖；
- 仅报告同场景可比结果；不可比项保留原因、版本和环境信息。

### Task 7：结果报告与文档

- 生成机器可读 JSON/JSONL/CSV 和人工可读 Markdown；
- 报告原始样本、聚合统计、失败配置、环境、版本、样本量和限制说明；
- 更新 `README.md`、`docs/DESIGN.md`、`docs/API.md`、`docs/ROADMAP.md`，必要时补充
  `docs/BENCHMARKS.md`；
- 不把一次本地小样本结果写成项目固定性能承诺。

## 7. 主要风险与控制措施

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

## 8. 测试要求

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

## 9. 量化验收标准

阶段 8 同时满足以下条件才算完成：

1. 新增离线测试不少于 30 个，且全量测试通过；
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

## 10. 完成定义

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

## 11. 建议提交节奏

```text
design(phase8): freeze observability and evaluation protocol
feat(observability): add trace span and run summary models
feat(observability): integrate lifecycle and checkpoint records
feat(benchmarks): add offline runner and sequential baseline
feat(benchmarks): measure parallel reliability and recovery scenarios
test(benchmarks): verify determinism security and comparability gates
docs: publish phase-8 evaluation results and limitations
```
