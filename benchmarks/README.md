# benchmarks — 离线评测与可观测性实验

阶段 8 的可观测性与评测实验包（与 `magent` 核心解耦，默认离线、确定性、不联网、不调真实 LLM、不抓 URL、不提交临时数据）。

## 运行

```bash
python -m benchmarks.cli --out benchmarks/out
```

输出（`benchmarks/out/`，已在 `.gitignore` 忽略）：

- `results.json`：整体结果（框架版本、数据集版本、场景统计、质量评测、参考对比）。
- `scenarios.csv`：每个场景的 `n/mean/median/p95/min/max` 与 `all_correct`。
- `REPORT.md`：人类可读摘要（含质量评测与参考框架对比，不排名）。

VulnTell 业务也可单独产出 trace：

```bash
python -m examples.vulntell --trace benchmarks/out/vulntell
# 写 benchmarks/out/vulntell.jsonl（Trace/Span）与 benchmarks/out/vulntell.summary.json（RunSummary）
```

## 版本（一并写入结果，保证可复现）

- `FRAMEWORK_VERSION`（来自 `benchmarks/__init__.py`）：本框架版本 `0.1.0`。
- `DATASET_VERSIONS`：`dataset_id=vulntell-demo`、`dataset_version=2024Q1`、`parser_version=1`、`dedup_version=1`、`metric_version=1`。
- 每个参考框架记录（LangGraph/AutoGen/CrewAI）携带 `version` 与 `behavior_note`，`status="not_comparable"`。

## 场景

| 场景 | 函数 | 验证点 |
|------|------|--------|
| 串行基线 | `run_sequential_baseline` | 单 worker 串行跑通，结果可复现 |
| 并行 DAG | `run_parallel` | fan-out/fan-in 下结果与串行一致（确定性） |
| Checkpoint 恢复 | `run_recovery` | 故障点之后重跑，结果不变（幂等/恢复） |
| 并行可靠性 | `run_reliability` | 注入 flaky + 超时节点，框架重试与超时计数正确 |

所有场景使用单调时钟计时；默认无随机性（如需随机须显式 seed）。

## VulnTell 源质量评测

`evaluate_vulntell_quality(meta, final_state)` 返回 `QualityReport`：

- `sample_count`、`insufficient_data`（样本低于阈值不排名）。
- `standardization`：必需字段存在率与无质量告警有效率。
- `dedupe`：仅有真值时计算 precision/recall/F1（真值见 `benchmarks/quality.EXPECTED_CANONICAL`）。
- `cross_source_consistency`：共享 CVE 跨源 `published_at` 一致。
- `report_completeness`、`partial_failure_usable`、`metric_reproducible`。

## 参考框架对比（不排名）

`collect_reference_comparison()` 仅记录各参考框架的版本与行为说明，`to_comparison_report()`
始终返回 `ranking=None`、`comparable=False`。本实验不替代、不评价外部框架，也不输出任何排名。

## 门禁

- 确定性：并行/不同并发度结果必须与串行基线一致。
- 隔离安全：启用观测不改变 VulnTell 报告与副作用；观测数据不含原始漏洞全文或凭据。
- 可复现：相同输入/配置多次运行指标一致。
- 样本不足：`insufficient_data=True` 时不计算无依据排名。
