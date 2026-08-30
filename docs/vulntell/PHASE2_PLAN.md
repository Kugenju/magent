# VulnTell 阶段 2：领域层迁移实施计划（已完成）

> 本文同时记录阶段 0–1 的完成审查结果，作为阶段 2 的进入基线。

## 1. 审查结论

当前工作区已经完成 VulnTell 阶段 0–2 的主要实现，但仍处于迁移开发工作区状态，尚未形成独立的阶段发布提交。

阶段 0 已完成：基线、确定性比较、部分失败、安全边界和恢复等价测试已经落地。

阶段 1 已完成：apps/vulntell 外壳、新 CLI、配置对象、应用生命周期、旧入口转发和新旧入口 contract tests 已落地。

阶段 2 已完成：领域实现已迁移到 apps/vulntell，阶段 0–1 的行为等价性保持不变。下一阶段进入阶段 3：Graph 与任务层迁移。

## 2. 证据与当前状态

### 2.1 阶段 0

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| 基线场景 | 已完成 | docs/vulntell/baseline.md、tests/contract/vulntell/baselines/ |
| 默认/无 LLM 确定性 | 已完成 | test_baseline_freeze.py |
| 单源失败降级 | 已完成 | baseline_faulty_cnvd.json、contract test |
| resume 等价与幂等 | 已完成 | baseline_resume.json、恢复测试 |
| Trace 脱敏 | 已完成 | trace contract test |
| 默认离线 | 已完成 | socket/connect 拦截测试 |
| 版本与报告比较规则 | 已完成 | tests/contract/vulntell/helpers.py |

### 2.2 阶段 1

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| apps.vulntell 包和入口 | 已完成 | apps/vulntell/__main__.py |
| 只读配置 | 已完成 | apps/vulntell/config.py |
| 应用生命周期 | 已完成 | apps/vulntell/application.py |
| 公共编排适配层 | 已完成 | examples/vulntell/run.py |
| 旧入口兼容转发 | 已完成 | examples/vulntell/__main__.py |
| 新旧入口等价 | 已完成 | tests/contract/vulntell/test_entrypoint_compat.py |
| 真实网络、API、Web、PostgreSQL | 未开始（符合计划） | 阶段 0–3 明确禁止 |

### 2.3 验证结果

本次审查执行结果：

- python -m pytest -q：286 passed；
- mypy src/magent：通过；
- python -m apps.vulntell --no-llm --json：成功；
- python -m examples.vulntell --no-llm --json：成功；
- 新旧入口报告确定性字段一致；
- Markdown 链接检查：0 个断链。

以上是当前工作区结果。阶段 0–2 的文件尚未全部提交为独立 release commit；下游 agent 开始阶段 3 前应先完成提交或明确保留当前工作区变更。

## 3. 当前架构事实

阶段 1 是“入口已迁移，业务实现未迁移”：

    apps/vulntell
        config.py
        application.py
        __main__.py
            ↓ 适配调用
    examples/vulntell
        run.py
        agents.py / graph.py / state.py
        models.py / normalize.py / dedupe.py
        metrics.py / report.py / db.py / sources.py

这符合阶段 1 设计，但不能被误认为 VulnTell 已完成目录迁移。

## 4. 尚未完成的阶段

| 阶段 | 状态 | 当前缺口 |
| --- | --- | --- |
| 阶段 2：领域层迁移 | 已完成 | domain、reporting、fixtures 已迁移；旧模块保留 re-export |
| 阶段 3：Graph/任务层迁移 | 已完成 | 详见 [PHASE3_RESULT.md](PHASE3_RESULT.md) |
| 阶段 4：数据源契约与增量 | 下一阶段 | 详见 [PHASE4_PLAN.md](PHASE4_PLAN.md) |
| 阶段 5：真实数据源 | 未开始 | HTTP adapter 仍为禁用接口 |
| 阶段 6：存储与查询 | 未开始 | 仍是示例 SQLite，无 repository/query service |
| 阶段 7：指标与报告产品化 | 未开始 | 指标和导出仍是示例级固定实现 |
| 阶段 8：CLI/API 任务服务 | 未开始 | 只有示例 CLI，无稳定 API |
| 阶段 9：安全/部署/发布 | 未开始 | 无服务认证、部署和运维闭环 |
| 阶段 10：兼容收口/看板 | 未开始 | 旧入口仍需经过弃用周期 |

magent 阶段 1–8 的能力已有测试覆盖；阶段 9 为候选发布状态。框架阶段完成不等于 VulnTell 产品完成。

## 5. 阶段 2 实施任务与验收（已完成）

### 5.1 目标

领域模型和纯业务规则已从 examples/vulntell 迁移到 apps/vulntell；新应用的领域层不再依赖旧目录，且阶段 0–1 的所有可观察行为保持不变。

阶段 2 完成后，examples/vulntell 的领域模块只剩 re-export；db、sources、state、agents、graph 和 run 仍作为阶段 3 的过渡实现。

### 5.2 目标目录

    apps/vulntell/
    ├── domain/
    │   ├── models.py
    │   ├── schemas.py
    │   ├── normalize.py
    │   ├── dedupe.py
    │   ├── metrics.py
    │   └── policies.py
    ├── reporting/
    │   ├── report.py
    │   └── exporters.py
    └── fixtures/
        ├── dataset_meta.json
        ├── nvd_sample.json
        └── cnvd_sample.json

阶段 2 可以暂时保留 examples/vulntell 的 db、sources、agents、graph、state，但新应用不得新增对旧领域模块的依赖。

### 5.3 任务拆分

#### Task 2.1：依赖和模块清单

建立迁移映射：

| 旧模块 | 新模块 | 类型 |
| --- | --- | --- |
| models.py | domain/models.py | 领域模型 |
| loading.py | domain/schemas.py 或 config.py | 数据集加载 |
| normalize.py | domain/normalize.py | 纯规则 |
| dedupe.py | domain/dedupe.py | 纯规则 |
| metrics.py | domain/metrics.py | 纯指标 |
| report.py | reporting/report.py | 报告组装/导出 |
| fixtures/ | apps/vulntell/fixtures/ | 应用数据 |

记录公开符号、输入输出类型和依赖，避免隐式改变 API。

#### Task 2.2：迁移模型和 schema

迁移 DatasetMeta、RawSourceRecord、SourceObservation、CanonicalVulnerability、QualityIssue、MetricSnapshot、Report 等模型。

要求：

- 保持字段名、类型、默认值和序列化格式；
- 明确 schema version；
- UTC 时间继续使用带时区类型；
- 原始载荷只保留 hash/ref；
- 未知、缺失和非法字段策略保持一致；
- 新模型不导入 magent 内部实现。

#### Task 2.3：迁移纯规则

迁移日期、CVSS、CWE、引用和产品字段标准化、质量问题、CVE 强匹配、pending、跨源冲突、volume/timeliness/completeness 指标以及结构化报告。

迁移完成后只保留一份真实实现，不得长期双写或双算。

#### Task 2.4：迁移 fixture 和路径解析

将 fixture 复制到 apps/vulntell/fixtures，并把路径解析集中到应用配置：

- 不依赖当前工作目录；
- CLI 和测试使用同一 fixture root；
- 保留 dataset id/version/window；
- 校验 fixture 版本；
- 不把数据库和 trace 输出提交到仓库。

#### Task 2.5：领域 contract tests

新增或迁移以下测试：

    test_models_round_trip_is_stable
    test_normalize_matches_baseline
    test_dedupe_matches_baseline
    test_metrics_matches_baseline
    test_report_matches_baseline
    test_invalid_fields_keep_quality_issues
    test_conflicts_are_traceable
    test_domain_has_no_network_or_framework_side_effect

测试直接调用 apps.vulntell.domain，不以 CLI 替代领域单元测试。

#### Task 2.6：切换应用依赖

导入方向应变为：

    apps.vulntell.application
        → apps.vulntell.domain / reporting
        → examples.vulntell.pipeline 过渡模块（如仍需要）

禁止：

    apps.vulntell.domain → examples.vulntell 领域模块
    src/magent → apps.vulntell

#### Task 2.7：清理和兼容

确认新旧入口使用同一份领域实现后：

- 删除旧领域模块，或改成明确的 re-export；
- 更新 docstring、README 和 import 示例；
- 在弃用周期内保留旧 import 的转发或可解释错误；
- 更新 coverage、mypy 和包路径检查。

### 5.4 阶段 2 验收标准

1. apps.vulntell.domain 和 apps.vulntell.reporting 可独立导入；
2. 新应用不再依赖旧目录领域实现；
3. 默认、无 LLM、单源失败、resume、trace 与阶段 0 基线等价；
4. canonical、pending、source_status、quality issues、metrics、report 逐字段一致；
5. 标准化、去重、指标和报告有直接 unit/contract tests；
6. fixture 路径与当前工作目录无关；
7. 无网络、外部命令和密钥依赖；
8. src/magent 无 VulnTell import；
9. 全量 pytest、mypy、离线 CLI 和链接检查通过；
10. 不存在双写、双算或随机选择结果；
11. 文档明确阶段 2 已完成、阶段 3 尚未开始；
12. 迁移差异、弃用策略和回滚方式有记录。

建议命令：

    python -m pytest -q tests/contract/vulntell
    python -m pytest -q tests/unit
    python -m apps.vulntell --no-llm --json
    python -m examples.vulntell --no-llm --json
    mypy src/magent
    git diff --check

## 6. 风险与控制

| 风险 | 控制 |
| --- | --- |
| Pydantic 序列化变化 | 使用冻结 baseline 逐字段比较 |
| 相对路径导致 fixture 不一致 | 所有路径从模块位置或配置解析 |
| 新旧模块循环导入 | 应用层单向组装，先画依赖图 |
| 两套实现结果漂移 | 迁移完成后只保留一份实现 |
| 误把 fixture 迁移当真实数据接入 | 阶段 2 明确禁止 live adapter |
| 为迁移修改 magent | 先在业务层修复；通用问题另开框架任务 |
| 删除旧模块导致外部 import 失败 | 保留短期 re-export/弃用提示 |

## 7. 后续阶段入口

阶段 2 已通过验收，进入阶段 3：

- 迁移 VulnTellState、Agent、Graph 和任务生命周期；
- 让 VulnTellApplication 不再依赖 examples.vulntell.run；
- 统一 full/incremental/resume/replay 任务模型；
- 保持 magent 执行语义不变。

阶段 3 已通过；下一阶段进入阶段 4 数据源契约设计。在 SourceAdapter、SourcePage、游标和错误语义冻结前，不接入真实 HTTP。

## 8. 下游 agent 交付格式

每个阶段 2 任务提交时必须说明：

1. Task 编号和范围；
2. 迁移、新增、删除的文件；
3. 新旧导入关系；
4. 测试命令和结果；
5. 与 baseline 的差异；
6. 是否改变 schema、报告、checkpoint 或公开入口；
7. 未解决风险和下一 Task 依赖。


