# VulnTell 阶段 0 基线冻结

本文档冻结 `examples.vulntell` 在迁移到 `apps/vulntell` 之前的“黄金基线”行为
（依据 `PHASE0_1_PLAN.md` Task 0.1）。

## 一、基线事实

| 项目 | 当前基线 |
| --- | --- |
| 入口 | `python -m examples.vulntell` |
| 数据模式 | fixture-first，默认离线 |
| fixture | `examples/vulntell/fixtures/`（`nvd_sample.json` / `cnvd_sample.json` / `dataset_meta.json`） |
| 数据集元信息 | `dataset_meta.json`（冻结窗口 `2023-01-01 .. 2023-12-31`，`framework_version` 取自已安装包元数据） |
| 运行状态 | `VulnTellState` |
| 持久化 | `VulnTellStore` + SQLite（默认 `:memory:`，业务库与框架 checkpoint 分离） |
| checkpoint | `SqliteCheckpointStore` + `SideEffectSink`（幂等 side-effect 工具） |
| LLM | 默认 `FakeProvider`（确定性 `echo:<input>`），可 `--no-llm` |
| 观测 | `--trace <prefix>` 输出 JSONL / summary（trace id 等运行标识不参与业务比较） |
| 框架版本 | 从已安装包元数据读取（`importlib.metadata.version("magent")`） |
| 退出码 | 成功 `0`，运行失败 `1`，`KeyboardInterrupt` `130` |

## 二、冻结的运行场景（机器可读快照）

位于 `tests/contract/vulntell/baselines/`，由 `generate_baselines.py` 从当前入口生成：

| 文件 | 场景 | 关键冻结值 |
| --- | --- | --- |
| `baseline_default.json` | 默认（含 FakeProvider 解释） | `nvd=ok, cnvd=ok`，canonical=5，pending=1，quality_issues=10 |
| `baseline_no_llm.json` | `--no-llm` | 同上确定性结果 |
| `baseline_faulty_cnvd.json` | `--faulty cnvd --no-llm` | `cnvd=failed, nvd=ok`，canonical=4，pending=0，quality_issues=7（部分失败） |
| `baseline_resume.json` | 完整运行后 `--resume`（同 checkpoint） | 与 `baseline_default` 业务等价 |
| `baseline_trace.summary.json` | `--trace` 的 summary 统计 | 结构化指标，已剥离 `trace_id` |

比较规则（`tests/contract/vulntell/helpers.py::normalize_report_for_compare`）：
- 指标数值、来源状态、实体数量、质量问题和版本字段必须相等；
- 嵌套 dict / list 按稳定业务键排序后比较；
- `generated_at` / `observed_at` 等非业务字段在比较时被剥离；
- resume 结果必须与完整运行结果业务等价；
- LLM 解释为确定性 `echo:`，单独保留、不参与确定性字段差异判定。

## 三、失败与安全边界（Task 0.4）

- `--faulty nvd` / `--faulty cnvd` 生成**部分报告**，失败来源显式标记（`source_status=<src>=failed`）；
- 默认运行**不进行任何网络请求**（仅读取本地 fixture）；
- 原始 `payload` 仅以 hash 进入 `State`，不进入 Trace / 日志 / LLM prompt；
- 不执行外部命令，不抓取引用 URL；
- 配置与状态/报告均**不保存 API key / token / cookie / 凭据明文**。

## 四、已知限制（迁移过渡期）

1. 阶段 0–2 已完成基线与领域层迁移；领域模块真实实现位于 `apps.vulntell/domain`，
   `examples.vulntell` 仅保留兼容 re-export。
2. 阶段 3 已完成：State、Graph、Agent 和任务生命周期真实实现位于
   `apps.vulntell.pipeline`；`examples.vulntell` 仅保留兼容转发。
3. `apps.vulntell` 默认 `--db` / `--checkpoint` 为 `:memory:`；`--resume` 必须与
   持久化 checkpoint 文件配合使用，禁止 `:memory:` + `--resume`。
4. 阶段 0–4 不接入真实 NVD / CNVD / CISA KEV，不引入 Web / API / 任务队列 / PostgreSQL。
5. `src/magent` 在阶段 0–3 不发生行为变更；本目录下的 commit 仅涉及 `apps/`、
   `examples/vulntell` 兼容入口、`tests/contract/vulntell` 与文档。

## 五、阶段 0 验收状态

- [x] 默认与 `--no-llm` 两次运行确定性字段一致（contract test 覆盖）
- [x] 单源失败仍有结构化报告且失败来源明确
- [x] resume 结果与无中断基线一致
- [x] trace summary 可生成且不含 `raw_payload` / 凭据 / 完整外部描述
- [x] 基线文件与比较规则已写入 `tests/contract/vulntell/` 与本文档
- [x] 工作区不提交数据库 / 缓存 / trace / 临时输出（`generate_baselines.py` 使用临时目录）
- [x] 阶段 0 不产生 `src/magent` 行为变更
