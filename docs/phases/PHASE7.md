# 阶段 7：VulnTell 纵向示例实施计划（已完成）

> **实施约束：** 本阶段首先冻结数据集、字段和指标定义，再开始编写 Agent。下游 Agent 不得
> 在没有 fixture、验收样例和版本号的情况下接入真实网络源或 LLM。

## 1. 阶段定位

阶段 1～6 已完成：`magent` 具备类型化 State、DAG 编排、并发 fan-out/fan-in、可靠性策略、
Checkpoint/恢复/幂等、Tool Registry、可选 LLM Provider 和 Middleware。阶段 7 已完成并提交；
当前全量离线测试为 211 个且全部通过。

阶段 7 不再扩展框架通用能力，而是使用现有 `magent` 实现一个可复现的 VulnTell 纵向示例，
验证框架能否支撑真实业务流程：多源漏洞情报采集、标准化、持久化、聚合、质量评估和报告生成。
业务代码必须位于 `examples/vulntell` 或独立业务包，不得把 CVE、NVD、CNVD、CVSS 等领域模型
加入 `src/magent` 核心。

## 2. 当前基线审视

### 已具备

- `BaseAgent`、`AgentResult`、Pydantic State 和状态合并；
- 条件路由、并发分支、join、reducer 和失败传播；
- 节点超时、显式重试、取消和结构化执行报告；
- SQLite Checkpoint、恢复、稳定 execution key 和 `SideEffectSink`；
- schema 校验的同步/异步 Tool、allowlist、限流、超时和脱敏；
- `FakeProvider`、可选 OpenAI adapter 和 Middleware；
- 离线示例、211 个测试和已提交的阶段 1～7 实现。

### 已交付

- `examples/vulntell` 领域模型、固定 NVD/CNVD fixture 和来源适配器；
- 确定性标准化、质量告警、跨源 CVE 去重和冲突可追溯；
- 业务 SQLite schema、事务写入、稳定唯一键和幂等副作用协议；
- 并发、可恢复、可处理部分来源失败的 VulnTell Graph；
- 固定数据集/时间窗口/版本元数据、确定性指标和 JSON/Markdown 报告；
- FakeProvider 解释边界、安全边界、恢复质量和端到端离线测试。

固定数据集和指标定义已冻结。尚未完成的“可重放评测、统一 trace、性能基准和参考框架
对比”属于阶段 8，不应倒填为阶段 7 的已交付内容。

## 3. 阶段目标

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

## 4. 范围与非目标

### 4.1 本阶段包含

- `examples/vulntell/models`：标准漏洞、来源观察、指标快照、报告和运行元数据；
- `examples/vulntell/fixtures`：脱敏、固定版本、可审计的 NVD/CNVD JSON 样本；
- `examples/vulntell/sources`：fixture adapter，以及隔离的真实 HTTP adapter 接口；
- `examples/vulntell/agents`：采集、标准化、去重、持久化、聚合、评估和报告 Agent；
- 业务 SQLite 表和幂等写入；
- 使用 `GraphBuilder` 的顺序/并发 DAG；
- 部分来源失败、Checkpoint 恢复和重复执行测试；
- 确定性指标计算、报告 JSON/Markdown 输出和离线 CLI；
- 业务层与 `magent` 核心的边界测试。

### 4.2 本阶段不包含

- 自动漏洞扫描、资产探测、漏洞利用、PoC 执行或攻击验证；
- 默认访问真实 NVD/CNVD 网络接口；
- 把历史论文数据直接宣称为当前真实统计结论；
- 让 LLM 决定漏洞评分、数据去重、时间窗口或来源排名；
- 自动抓取引用 URL、执行网页脚本或处理不受信任的远程代码；
- 分布式采集、消息队列、实时流处理和多租户服务；
- 完整 Web 前端和生产级数据仓库。

## 5. 业务模型设计

### 5.1 原始记录与标准实体分离

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

### 5.2 标准化字段

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

### 5.3 去重和匹配

首版优先采用可解释规则：

1. 合法 CVE ID 作为强匹配键；
2. 来源记录 ID 作为来源内幂等键；
3. 无 CVE ID 的记录进入待匹配集合，不直接强行合并；
4. 模糊匹配必须保留候选、规则版本和置信等级，不能静默覆盖；
5. 同一字段冲突保留各来源值，由聚合层按明确优先级或字段策略处理。

去重结果必须可以由输入记录、匹配规则版本和 parser version 重新计算。

## 6. 业务 Graph 与执行语义

### 6.1 推荐流程

```text
source_nvd ─────┐
                ├→ normalize_nvd ─┐
source_cnvd ────┘                 ├→ deduplicate → persist
                └→ normalize_cnvd ┘                  ↓
                                           aggregate → evaluate → report
```

NVD/CNVD 采集和标准化属于独立分支，使用阶段 3 的分支隔离和 join reducer。分支不能直接修改
另一个来源的中间列表；join 后才进行跨源合并。

### 6.2 部分失败

业务层不应简单复用框架的 `fail_fast` 作为最终产品策略。首版可采用：

- 采集分支失败：保留其他来源，记录 `source_status=failed` 和错误摘要；
- 标准化单条记录失败：跳过该记录并记录质量告警，不丢弃整个来源；
- 去重/持久化 schema 错误：停止运行，避免产生不可信报告；
- 指标样本不足：输出 `insufficient_data`，不进行无依据排名；
- 报告生成失败：保留结构化指标和机器可读 JSON，文字报告标记失败。

部分失败语义必须体现在 State 和最终报告中，不能只写日志。

### 6.3 Checkpoint、恢复与幂等

- 每个采集/标准化分支使用稳定 `workflow_version` 和节点 `version`；
- 长耗时或有副作用节点使用 `SqliteCheckpointStore`；
- 业务写入通过业务唯一键与 `SideEffectSink` 共同防止重复；
- 恢复后已提交分支不得重复执行，未提交分支可以重放；
- 真实来源 adapter 的请求重试必须遵守阶段 4 的 timeout、retryable error 和限流策略；
- 远程请求结果只能在成功校验后进入业务 State；
- EventBus 仅用于观测，不能作为业务数据源或恢复依据。

## 7. 指标与评估设计

### 7.1 时间窗口和版本

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

### 7.2 首版确定性指标

- 数据量：记录数、唯一漏洞数、更新记录数；
- 时效性：观测时间与来源时间的延迟分布；
- 完整性：必需字段的存在率与有效率分开计算；
- 维护性：窗口内更新频率和间隔分布；
- 可验证性：有效引用率、可回溯字段比例；
- 相关性：根据预先声明的技术栈/行业画像计算匹配率；
- 相对独立性：当前观测范围内的首次观察比例，不解释为真实原创率。

指标函数必须是纯函数或依赖显式输入，不读取系统当前时间、随机数或网络。CISA KEV 等职责
不同的数据源若加入后，应使用专门指标，不能直接与 NVD/CNVD 做同口径排名。

### 7.3 LLM 使用边界

LLM 只可用于：

- 对结构化指标生成自然语言解释；
- 把已验证字段组织成报告草稿；
- 对数据质量告警生成辅助说明。

LLM 不得修改 canonical entity、去重结果、基础指标、最终排名或来源状态。LLM 失败时必须仍
能输出结构化报告；Fake Provider 用于默认离线测试。

## 8. 数据库与安全要求

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

## 9. 推荐任务拆分

### Task 0：业务边界和数据集冻结

整理论文材料中可复用的字段、时间窗口和指标定义；确定 fixture 许可证、来源说明、数据集 ID、
版本和脱敏规则。不得把论文历史结论直接写成运行结果。

### Task 1：领域模型与 fixture

实现 Pydantic 领域模型、JSON fixture、schema 版本和加载器。覆盖缺失字段、非法时间、重复
source record 和未知字段策略。

### Task 2：来源适配器

实现统一 SourceAdapter 协议和 NVD/CNVD fixture adapter；定义真实 HTTP adapter 的隔离接口，
但默认不联网。记录来源状态、解析错误和原始载荷 hash。

### Task 3：标准化与质量问题

实现日期、CVSS、CWE、引用和受影响产品的确定性解析；区分 missing、invalid、ambiguous，
生成结构化 `QualityIssue`。

### Task 4：去重、聚合与持久化

实现 CVE 强匹配、待匹配集合、字段冲突保留、跨源聚合和业务 SQLite schema。使用唯一键、
事务和 `SideEffectSink` 验证重复运行幂等。

### Task 5：VulnTell Graph

使用 `GraphBuilder` 构造采集→标准化→join→去重→持久化→评估→报告流程；验证分支隔离、
部分失败、checkpoint 恢复、节点版本和最终状态可追溯。

### Task 6：指标与报告

实现固定窗口、指标版本、样本量门槛、CISA 等不同职责源的扩展位和 JSON/Markdown 报告。报告
必须同时包含数据集、版本、窗口、失败来源、质量告警和计算版本。

### Task 7：可选 LLM 解释

用 Fake Provider 为结构化指标生成可重复解释；验证 LLM 不能修改确定性结果，Provider 失败时
报告仍可生成。真实 Provider 只作为显式 smoke test。

### Task 8：CLI、测试和发布

提供 `python -m examples.vulntell` 或等价离线 CLI；补充边界、安全、恢复和性能测试；更新
README、`API.md`、`DESIGN.md`、`ROADMAP.md`，形成阶段 7 独立提交。

## 10. 测试要求（验收记录）

阶段 7 已新增 43 个有意义的离线测试，并保留阶段 1～6 全部回归；以下清单均已完成：

### 数据和标准化

- [x] fixture 加载、版本和许可证元数据校验；
- [x] 合法/非法 CVE、时间、CVSS、CWE 和引用解析；
- [x] 缺失、无效、歧义字段分别产生对应质量问题；
- [x] 原始记录 hash 稳定，重复 source record 可识别；
- [x] 不同来源同一 CVE 能合并，缺少 CVE 的记录不被强行合并；
- [x] 字段冲突可追溯且遵守声明的聚合策略。

### Graph、恢复和持久化

- [x] NVD/CNVD 分支并发执行，分支状态互不污染；
- [x] 一个来源失败时仍生成部分结果和失败摘要；
- [x] join 等待成功分支并正确处理部分失败语义；
- [x] 中断后从最近成功 checkpoint 恢复，已提交节点不重跑；
- [x] 重复运行不产生重复 observation、entity 和 metric；
- [x] 业务唯一键、execution key 和 SQLite 事务共同生效；
- [x] schema/version 不兼容时明确拒绝恢复。

### 指标、报告和 LLM 边界

- [x] 固定窗口和 fixture 下指标结果可重复；
- [x] 样本不足返回 `insufficient_data`，不输出虚假排名；
- [x] 指标版本、数据集版本和窗口出现在报告中；
- [x] LLM 解释失败不影响结构化报告；
- [x] LLM 输出不能修改评分、去重或来源状态；
- [x] Fake Provider 无网络、无 API Key 时稳定运行。

### 安全和质量

- [x] 恶意漏洞描述不会改变工具 allowlist 或执行权限；
- [x] 默认 CLI 不发起网络请求、不抓取引用、不执行命令；
- [x] 日志、State、checkpoint 和报告不包含 API Key；
- [x] 业务包不被 `magent` 核心导入，核心无漏洞领域依赖；
- [x] 全量测试、类型检查、导入检查和离线 CLI 通过。

## 11. 量化验收标准

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

## 12. 完成定义

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

## 13. 建议提交节奏

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
