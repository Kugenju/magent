# VulnTell 产品化实施路线图

## 1. 使用方式

本文是下游 agent 的执行路线图。每一阶段必须先完成目标和验收，再进入下一阶段；未通过门禁时，不应并行扩展更高层功能。

总策略：先迁移和冻结边界，再接入真实数据源；先 CLI/定时任务，再 API/服务化；先单机可靠性，再评估是否需要分布式。

## 2. 阶段总览

| 阶段 | 名称 | 预计 | 主要产出 |
| --- | --- | ---: | --- |
| 0 | 基线冻结与决策 | 2–3 天 | 基线报告、兼容策略、数据许可清单 |
| 1 | apps/vulntell 外壳 | 2–3 天 | 新入口、配置对象、兼容启动器 |
| 2 | 领域层迁移（已完成） | 1 周 | domain/reporting 模块、结果等价测试 |
| 3 | Graph 与任务层迁移（已完成） | 1 周 | pipeline、Application、业务 Graph、恢复入口 |
| 4 | 数据源契约与增量模型（已完成） | 3–5 天 | SourceAdapter、分页/游标、SyncRun、离线同步骨架 |
| 5 | 真实数据源接入（收尾中） | 3–5 周 | NVD/CNVD/CISA KEV adapter、live pipeline |
| 6 | 存储与查询（下一阶段） | 2–4 周 | schema v2、repository、SQLite/PostgreSQL、查询 |
| 7 | 指标与报告产品化 | 2–3 周 | 版本化指标、质量回归、导出 |
| 8 | CLI、API 与任务服务 | 2–4 周 | CLI 命令、API、任务状态 |
| 9 | 安全、部署与发布 | 3–6 周 | 认证、审计、部署、发布包 |
| 10 | 兼容收口与可选看板 | 3–5 周 | 弃用旧入口、独立看板（可选） |

阶段 0–4 是迁移基础，阶段 5–7 形成最小可用工具，阶段 8–9 面向生产服务，阶段 10 不阻塞核心工具交付。

## 3. 阶段 0：基线冻结与决策

### 目标

- 固定当前 examples/vulntell 的 fixture、数据集、指标和报告输出；
- 明确新旧入口、版本、配置、数据库和 checkpoint 位置；
- 确认数据源许可、真实网络开关和未来打包策略。

### 工作项

1. 保存默认、--no-llm、--faulty、--resume 和 --trace 的结构化结果；
2. 建立报告逐字段 diff 工具或测试夹具；
3. 列出当前已知限制和迁移期间不改变的语义；
4. 定义 application_version、workflow_version 和 schema version。

### 验收标准

- 当前全量测试通过；
- 连续两次运行报告一致；
- 新旧输出存在可自动比较的基线；
- 数据源许可和敏感字段清单有文档记录；
- 明确 examples.vulntell 的兼容周期。

### 禁止事项

不接真实网络、不重写 magent、不同时开发 Web 看板。

## 4. 阶段 1：创建 apps/vulntell 外壳

### 目标

建立新的应用入口和依赖组装层，暂时复用旧业务实现，证明迁移路径可行。

### 工作项

- 创建 apps 和 apps/vulntell 包；
- 增加 config.py 与 application.py；
- 实现 python -m apps.vulntell；
- 将 examples/vulntell 改为薄兼容入口；
- 明确 fixture、数据库和 checkpoint 的路径解析方式。

### 验收标准

- 新旧 CLI 均能执行默认、JSON、无 LLM、故障和 trace 场景；
- 新旧结构化报告一致；
- 应用启动不要求 API Key 或网络；
- 没有复制第二份业务实现。

## 5. 阶段 2：领域层迁移（已完成）

### 目标

领域模型和纯业务规则已迁移到 apps/vulntell/domain，输入输出保持不变。详细完成记录见 [PHASE2_RESULT.md](PHASE2_RESULT.md)。

### 工作项

- 迁移 models/loading/normalize/dedupe/metrics/report；
- 拆分 schema、策略和报告导出职责；
- 为标准化、去重、指标补充纯函数 unit tests；
- 将 fixture 移到应用拥有的位置，并使用稳定路径加载。

### 验收标准

- 领域模块不导入 examples.vulntell；
- magent 不导入 VulnTell；
- 旧 fixture 的报告逐字段等价；
- 缺失、非法、歧义和冲突字段均保留质量问题；
- 领域函数不读取系统时间、随机数或网络。

## 6. 阶段 3：Graph 与任务层迁移（已完成）

### 目标

建立 pipeline、VulnTellApplication、VulnTellState、业务 Graph 和任务服务，移除 Application 对 examples.vulntell.run/state 的运行时依赖。详细计划见 [PHASE3_PLAN.md](PHASE3_PLAN.md)，完成记录见 [PHASE3_RESULT.md](PHASE3_RESULT.md)。

### 工作项

- 已迁移 agents/graph/state 至 `apps.vulntell.pipeline`，`examples.vulntell.{state,agents,graph,run}` 现为薄壳转发；
- 依赖注入 adapter（经 `sources/legacy`）、repository（经 `storage/legacy`）、checkpoint、provider 和 sink；
- 明确 full run 与 resume 的任务类型（`VulnTellJobRunner`）；
- 保留部分失败、幂等和 LLM 边界。

### 验收标准

- 并发采集、join、持久化、评估和报告流程通过端到端测试；
- 单源失败仍可生成部分报告；
- 中断恢复不重跑已提交节点；
- 重复执行不新增 observation/entity/metric；
- Trace 不包含 raw payload 和凭据。

## 7. 阶段 4：数据源契约与增量模型（已完成）

### 目标

详细实施方案见 [PHASE4_PLAN.md](PHASE4_PLAN.md)，审查记录见 [PHASE4_REVIEW.md](PHASE4_REVIEW.md)。阶段 4 协议、fixture、错误分类、恢复和测试门禁已通过。

在接入真实网络前冻结 SourceAdapter、分页/游标、同步运行和错误语义。

### 工作项

- 已定义 SourceRequest、SourcePage、SourceRecord、SyncRun、SyncPageCheckpoint（见 `protocol.py`、`domain/models.py`）；
- 已实现 PagedFixtureSource 支持分页、空页、重复页、乱序、坏记录和中断注入（见 `fixtures.py`）；
- 已定义 SourceErrorKind（rate_limited/timeout/transient/invalid_response/auth/forbidden/not_found/permanent/cancelled）和 classify_http_status/classify_exception（见 `errors.py`）；
- 已实现 SyncRunner/SyncRunnerService，支持 run/resume/cancel、状态完成、重试游标和 checkpoint 幂等。

### 验收标准

- fixture 故障注入与专门的 `tests/unit/test_sources.py`、`tests/unit/test_sync.py` 已覆盖；
- 分页中断恢复和 checkpoint contract 已通过；
- 重复页不会导致重复写入（page fingerprint 去重）；
- adapter import 和默认 CLI 完全离线；
- 错误分类可被 magent retry policy 正确消费（retryable 字段）。

## 8. 阶段 5：真实数据源接入（已完成）

阶段 5 实施计划见 [PHASE5_PLAN.md](PHASE5_PLAN.md)，完成记录见 [PHASE5_RESULT.md](PHASE5_RESULT.md)，审查记录见 [PHASE5_REVIEW.md](PHASE5_REVIEW.md)，收尾记录见 [PHASE5_CLOSEOUT_RESULT.md](PHASE5_CLOSEOUT_RESULT.md)。

### 目标

逐个接入 NVD、CISA KEV、CNVD，保持 fixture/live 双轨。

### 推荐顺序

1. NVD：先验证分页、CVSS 和产品映射；
2. CISA KEV：验证专用指标和状态模型；
3. CNVD：验证中文字段、来源差异和冲突保留。

### 每个来源必须完成

- 许可、字段映射和版本文档；
- endpoint、认证、限速和响应大小策略；
- 分页/游标和增量边界；
- retry/timeout/cancellation 接入；
- fixture、contract tests 和独立 smoke test；
- 原始 payload hash/ref 和脱敏策略；
- 单条坏记录隔离和来源级失败报告。

### 验收标准

- 默认命令仍不联网；
- live 模式必须显式开关；
- 429、超时和临时错误按策略重试；
- 进程重启后从最近成功游标恢复；
- 连续两次相同窗口同步结果一致；
- 不抓取引用网页，不执行任何外部代码。

## 9. 阶段 6：存储与查询

### 目标

将当前业务 SQLite 扩展为可迁移、可查询、可替换的存储层。

### 工作项

- 设计 schema v2、索引、唯一键和迁移脚本；
- 定义 repository protocol；
- 完善 SQLite 批量写入和事务；
- 实现 PostgreSQL 适配或至少完成接口和集成测试；
- 增加 CVE、来源、严重性、时间、产品和质量状态查询；
- 增加冲突审计和同步运行查询。

### 验收标准

- 重复导入不增加逻辑重复记录；
- 批次部分提交和恢复行为明确；
- schema 升级可回滚或明确拒绝；
- SQLite 与 PostgreSQL 的 contract tests 一致；
- 查询支持分页、稳定排序和输入校验；
- 原始载荷不进入默认 State、Trace、日志和 LLM prompt。

## 10. 阶段 7：指标与报告产品化

### 目标

让评估结果具备版本化、可比较、可解释和可导出能力。

### 工作项

- 抽象指标配置和版本；
- 增加标注集、precision/recall/F1 和回归样例；
- 区分存在率、有效率、时效性、维护性、可验证性和独立性；
- 增加样本不足状态和不排名规则；
- 增加 JSON/Markdown/CSV 导出；
- 保持 LLM 解释字段与确定性指标隔离。

### 验收标准

- 相同数据集、窗口和版本产生相同指标；
- 报告包含来源状态、质量告警、窗口和所有版本字段；
- 样本不足时明确 insufficient_data，不输出排名；
- LLM 失败不影响结构化报告；
- 导出内容不含密钥和未经控制的原始外部文本。

## 11. 阶段 8：CLI、API 与任务服务

### 目标

提供稳定的用户入口，同时保持执行任务与请求生命周期解耦。

### 工作项

- 完成 source/sync/run/resume/query/report/inspect CLI；
- API 提供任务、漏洞、来源观察、质量问题、报告和健康检查；
- CLI/API 共用 application service；
- 增加任务状态、取消、重试和结果分页；
- 明确 API 认证、限流和审计接口。

### 验收标准

- CLI 与 API 对同一运行使用相同业务服务；
- API 不直接操作内部 State 或数据库连接；
- 长任务可异步提交、查询、恢复和取消；
- API 错误可定位且不泄露凭据；
- 默认开发模式仍可完全离线运行。

## 12. 阶段 9：安全、部署与发布

### 目标

将工具提升为可部署的单机/服务版本，并完成安全和运维收口。

### 工作项

- 认证、授权、审计和敏感字段脱敏；
- SSRF、URL allowlist、Prompt Injection 隔离；
- 密钥管理、数据保留、备份和恢复；
- 容器化、配置模板、健康检查和故障演练；
- CI 覆盖离线测试、类型检查、构建、安全扫描和迁移测试；
- 冻结 VulnTell 与 magent 版本兼容策略。

### 验收标准

- 安全测试覆盖 SSRF、恶意文本、超大响应、凭据泄露和越权；
- 备份后可恢复数据库和 checkpoint；
- 单机故障演练结果可追踪；
- 生产配置不依赖源码内密钥；
- 构建产物、依赖和许可证清单完整；
- 发布说明明确已实现能力和非目标。

## 13. 阶段 10：兼容收口与可选看板

### 目标

在核心工具稳定后完成旧入口弃用，并独立评估 Web 看板。

### 工作项

- examples.vulntell 输出弃用提示并只做转发；
- 更新 README、示例、CI 和外部文档；
- 根据安装、部署和协作边界决定是否拆分仓库；
- 看板单独目录、依赖和验收，不修改核心执行协议。

### 验收标准

- apps.vulntell 是唯一完整实现；
- 旧入口在约定周期内可用，之后按版本策略移除；
- 看板故障不影响 CLI/API/数据管道；
- 拆分仓库前已有版本化 magent 依赖和 contract tests。

## 14. 阶段依赖

    0 基线冻结
       ↓
    1 应用外壳 → 2 领域迁移 → 3 Graph 迁移
                                  ↓
                         4 数据源契约
                                  ↓
                         5 真实来源 ─┐
                                      ├→ 6 存储查询 → 7 指标报告
                                      │                    ↓
                                      └──────────────→ 8 CLI/API → 9 服务化 → 10 看板/拆分

阶段 5、6 可以有限并行，但必须先完成阶段 4 的契约。阶段 8 之前不应承诺稳定 Web API。阶段 10 不得反向阻塞阶段 7 的 MVP。

## 15. 每阶段统一质量门禁

- 全量现有测试通过；
- 新增 unit、contract、integration 测试；
- 默认 fixture 流程离线运行；
- 重复运行幂等；
- Checkpoint 恢复结果与基线一致；
- 部分来源失败行为明确；
- Trace、日志、报告不包含敏感数据；
- 文档链接、命令和 schema 版本同步；
- 任何 magent 修改都有通用最小复现和回归测试。

## 16. 下游 agent 工作协议

每个任务提交时必须包含：

1. 所属阶段和不在范围内的内容；
2. 代码、文档和测试变更清单；
3. 可复现命令和测试结果；
4. 对执行语义、状态 schema、checkpoint 或 API 的影响；
5. 是否需要更新版本、迁移说明和安全文档；
6. 未解决问题、风险和下一阶段依赖。

下游 agent 不得在未通过当前阶段门禁时跨阶段实现；不得为了业务方便绕过 magent 的重试、取消、Checkpoint、工具 allowlist 或状态校验。

## 17. 预计交付节点

- 迁移完成：阶段 0–3，通过新旧结果等价和恢复测试；
- 离线 MVP：阶段 4、6、7 完成，支持稳定的 fixture/定时任务/CLI；
- 真实数据 MVP：阶段 5 完成至少三个来源；
- 服务候选版：阶段 8–9 完成，具备 API、认证、审计和部署文档；
- 最终产品版：阶段 10 完成兼容收口；看板和拆仓库按独立决策执行。
