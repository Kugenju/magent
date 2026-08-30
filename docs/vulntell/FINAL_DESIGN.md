# VulnTell 最终框架实现设计

## 1. 目标与边界

本文定义 VulnTell 从 examples/vulntell 演进为 apps/vulntell 产品应用后的目标架构，作为下游 agent 的实现基线。

最终工具应完成漏洞情报的采集、增量同步、标准化、质量检查、跨源去重、持久化、查询、指标评估和报告输出，并支持失败恢复、幂等运行、审计和可观测性。

不包含漏洞扫描、资产探测、PoC、漏洞利用、攻击验证、外部代码执行和默认抓取引用网页。

magent 负责“如何可靠执行”；VulnTell 负责“处理什么漏洞情报以及如何解释”。CVE、NVD、CNVD、CISA KEV、CVSS 和来源质量规则不得进入 src/magent。

## 2. 设计原则

1. 渐进迁移：不一次性重写，先建立兼容入口，再逐模块迁移。
2. 稳定核心：复用 magent 的 Agent、Graph、Retry、Checkpoint、Tool、LLM 和 Observability 语义。
3. 离线优先：fixture、FakeProvider 和临时数据库是默认测试路径；真实网络必须显式开启。
4. 确定性优先：标准化、去重、基础指标和来源状态由规则决定；LLM 只能提供非约束性解释。
5. 可恢复与幂等：同步、批处理和持久化均支持断点恢复，重复执行不产生重复业务数据。
6. 可追溯：结果必须关联数据集、来源记录、解析器、规则和运行版本。
7. 最小权限：工具 allowlist、URL 策略、输入大小限制、凭据隔离和日志脱敏默认开启。
8. 可替换存储：SQLite 用于本地和测试；生产存储通过 repository 协议接入 PostgreSQL。

## 3. 系统边界

    apps/vulntell
    Config / CLI / API / Jobs / Domain / Sources / Storage
    Normalize / Dedupe / Metrics / Reports / Security
                         │ public API only
                         ▼
    src/magent
    Agent / Typed State / Graph / Executor / Retry / Checkpoint
    Tools / LLM Provider / Middleware / EventBus / Observability
                         │
          SQLite / PostgreSQL    NVD / CNVD / CISA KEV / fixtures

apps/vulntell 负责数据源、领域模型、同步任务、repository、业务 Graph、CLI、API、报告和业务安全策略。

magent 负责 Agent 生命周期、状态合并、DAG 调度、重试/超时/取消、Checkpoint/恢复、工具/LLM 扩展和执行观测。

## 4. 目标目录

    apps/
    ├── __init__.py
    └── vulntell/
        ├── __init__.py
        ├── __main__.py
        ├── config.py
        ├── application.py
        ├── domain/
        │   ├── models.py
        │   ├── schemas.py
        │   ├── normalize.py
        │   ├── dedupe.py
        │   ├── metrics.py
        │   └── policies.py
        ├── sources/
        │   ├── base.py
        │   ├── fixture.py
        │   ├── nvd.py
        │   ├── cnvd.py
        │   ├── cisa_kev.py
        │   └── security.py
        ├── pipeline/
        │   ├── state.py
        │   ├── agents.py
        │   ├── graph.py
        │   └── jobs.py
        ├── storage/
        │   ├── protocol.py
        │   ├── sqlite.py
        │   ├── postgres.py
        │   └── migrations/
        ├── reporting/
        │   ├── report.py
        │   └── exporters.py
        ├── api/
        │   ├── schemas.py
        │   ├── routes.py
        │   └── service.py
        ├── security/
        │   ├── redaction.py
        │   ├── url_policy.py
        │   └── prompt_policy.py
        └── fixtures/

examples/vulntell 在迁移期间只保留兼容启动器或 re-export，不再添加新业务实现。

## 5. 数据模型与版本

核心对象：

    RawSourceRecord        来源原始记录和 payload hash/ref
    SourceObservation      一个来源对一个漏洞的标准化观察
    CanonicalVulnerability 跨来源归并后的漏洞实体
    QualityIssue           缺失、非法、歧义或冲突
    MetricSnapshot         固定窗口和版本下的指标
    SyncRun                一次同步的状态、游标和统计
    EvaluationRun          一次评估/报告运行元数据

每次运行至少记录 dataset_id、dataset_version、window_start、window_end、observed_at、source、source_record_id、parser_version、schema_version、deduplication_version、metric_version、framework_version、application_version、run_id、workflow_version 和 node_version。

时间统一使用带时区的 UTC。未知、缺失和非法字段不能用默认值混淆。原始载荷只保存受控 hash/ref，不把不受限的完整文本放入 State、Trace 或 LLM prompt。

## 6. 数据源适配器

统一协议必须同时支持 fixture 和 HTTP：

    class SourceAdapter(Protocol):
        source: str
        async def fetch(request, *, cursor=None, runtime) -> SourcePage: ...

SourcePage 至少包含 records、next_cursor、has_more、observed_at、source_version 和响应摘要。

每个真实来源必须独立实现分页/游标、限速、超时、429、临时错误、响应 schema、数据许可、凭据和 fixture。HTTP 适配器不得在 import 时联网，默认 CLI 不得构造 live adapter。

## 7. 业务 Graph

    load_config
        ↓
    create_sync_run
        ↓
    collect_nvd ─────┐
    collect_cnvd ────┼→ normalize_* ─→ join ─→ dedupe
    collect_kev ────┘                         ↓
                                      persist_batch
                                             ↓
                                      evaluate_metrics
                                             ↓
                                      build_report
                                             ↓
                                      export / query API

采集分支允许部分失败但必须记录来源状态和错误摘要；单条标准化失败只隔离该记录并产生 QualityIssue；去重或持久化 schema 错误停止运行；持久化通过业务唯一键和 SideEffectSink 双重保证幂等；EventBus 和 Trace 只能旁路观测。

## 8. 存储与查询

建议业务表：

    raw_source_records
    source_observations
    canonical_vulnerabilities
    vulnerability_conflicts
    quality_issues
    sync_runs
    sync_cursors
    metric_snapshots
    evaluation_runs

关键唯一约束包括 (source, source_record_id)、cve_id 和批次/窗口组合键。Repository 层不得暴露 SQLite 连接细节。查询至少支持 CVE、来源、严重性、发布时间、更新时间、产品和质量状态，并提供分页和稳定排序。

## 9. CLI、API 与报告

CLI 与 API 共用 application service，不复制业务逻辑。

建议 CLI：

    vulntell source list
    vulntell sync [--source ...] [--since ...] [--live]
    vulntell run [--dataset ...]
    vulntell resume --run-id ...
    vulntell query [filters]
    vulntell report --run-id ... --format json|markdown|csv
    vulntell inspect --run-id ...

API 初期提供任务、漏洞查询、来源观察、质量问题、报告和健康检查。API DTO 不直接序列化内部 VulnTellState。

报告必须包含结构化指标、来源状态、失败摘要、质量告警、数据集窗口和版本信息。LLM 输出放在独立 explanation 字段，不能覆盖确定性字段。

## 10. 安全

- live 模式显式开启，endpoint 使用 allowlist；
- HTTP 响应限制大小，禁止跟随不受信任的引用链接；
- 外部漏洞文本视为不可信输入，进入 LLM 前需截断、隔离和脱敏；
- API Key、Cookie、Authorization 和原始敏感载荷不进入 State、Checkpoint、Trace 或默认日志；
- 工具调用经过 Registry、schema、allowlist、超时和幂等策略；
- 不执行外部命令、动态脚本、PoC 或远程代码；
- API 具备认证、限流、审计和输入校验；
- fixture、真实数据和生成报告的许可与保留策略写入文档。

## 11. 打包与部署

迁移初期 apps/vulntell 是源码仓库应用，通过 checkout 运行；magent 仍可独立安装。产品化后再决定保留 monorepo 并增加 VulnTell 依赖组，或将 VulnTell 打成依赖固定版本 magent 的独立发行包。

在没有独立版本、部署和 CI 需求前，不拆仓库。无论采用哪种方案，都必须保留 contract/integration tests。

## 12. 框架迭代规则

业务问题先建立最小复现并分类。CVE 字段、来源协议、指标和报告问题留在 VulnTell；通用调度、批处理、背压、Checkpoint、恢复或工具生命周期问题才进入 magent。

框架变更必须新增通用测试、更新 API/迁移说明，并通过全部 VulnTell contract tests。不得因单一来源特殊行为修改通用执行语义。

## 13. 最终完成定义

1. fixture 和至少三个真实来源适配器通过 contract tests；
2. 支持全量、增量、分页、游标、断点恢复和重复运行幂等；
3. SQLite 本地稳定，PostgreSQL 适配和迁移策略可验证；
4. 可按 CVE、来源、严重性、时间和产品查询；
5. 报告包含质量、来源状态、确定性指标和完整版本元数据；
6. 采集部分失败、单条脏数据、429、超时、进程重启均有可验证行为；
7. CLI、API、Trace、Checkpoint 和审计路径可用；
8. 默认流程离线且无密钥，live 模式有安全边界；
9. 安全、数据许可、备份恢复和部署文档完成；
10. 所有框架修改都有通用复现、回归测试和迁移说明。
