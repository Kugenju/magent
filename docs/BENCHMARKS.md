# 阶段 8 评测结果与复现说明

本文件汇总 `benchmarks/` 离线评测的设计、复现入口与结果解释边界。实验代码与运行方式见
[`benchmarks/README.md`](../benchmarks/README.md)。

## 复现入口

```bash
pip install -e ".[dev]"          # 干净环境可编辑安装，无需网络/API Key
python -m benchmarks.cli --out benchmarks/out   # 写 results.json / scenarios.csv / REPORT.md
python -m examples.vulntell --trace benchmarks/out/vulntell   # 生成 Trace/Span/RunSummary
```

所有实验默认离线、确定性，不联网、不调真实 LLM、不抓取 URL、不提交临时数据
（`benchmarks/out/` 已在 `.gitignore` 忽略）。

## 版本信息（随结果一并写入）

- `FRAMEWORK_VERSION = 0.1.0`
- `DATASET_VERSIONS`：`dataset_id=vulntell-demo`、`dataset_version=2024Q1`、`parser_version=1`、
  `dedup_version=1`、`metric_version=1`
- 参考框架记录（LangGraph/AutoGen/CrewAI）：`status="not_comparable"`，`ranking=None`

## 场景与验证点

| 场景 | 验证点 |
|------|--------|
| 串行基线 | 单 worker 串行跑通，结果可复现 |
| 并行 DAG | fan-out/fan-in 下结果与串行一致（确定性） |
| Checkpoint 恢复 | 故障点之后重跑，结果不变（幂等/恢复） |
| 并行可靠性 | 注入 flaky + 超时节点，框架重试与超时计数正确 |

## VulnTell 源质量评测

`evaluate_vulntell_quality(meta, final_state)` 返回 `QualityReport`：

- `sample_count`、样本不足时 `insufficient_data=True`（不排名）；
- `standardization`：必需字段存在率与无质量告警有效率；
- `dedupe`：仅有真值时计算 precision/recall/F1（真值见 `benchmarks/quality.EXPECTED_CANONICAL`）；
- `cross_source_consistency`：共享 CVE 跨源 `published_at` 一致；
- `report_completeness`、`partial_failure_usable`、`metric_reproducible`。

全量测试基线：**250 passed**，`mypy src/magent` 通过；Phase 8 新增离线测试 39 个。

## 结果解释边界（重要）

- 以上为**单次本地小样本**结果，不构成项目固定性能承诺；
- 参考框架对比**不排名**，仅记录版本与行为说明，不替代/评价外部项目；
- 评测使用脱敏 fixture，报告不代表当前真实漏洞情报统计；
- 并行/不同并发度结果必须与串行基线一致，否则视为回归。
