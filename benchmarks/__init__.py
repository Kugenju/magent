"""阶段 8 评测、可观测性与对比实验（Task 0）。

本目录包含离线实验与观测能力，位于 `magent` 核心之外：

- ``benchmarks/config.py``  实验配置（冻结数据集/窗口/版本/并发/重复次数）
- ``benchmarks/stats.py``   重复运行统计（n/mean/median/p95/min/max）
- ``benchmarks/runner.py``  固定配置、可重放的实验运行器
- ``benchmarks/scenarios.py`` 串行基线、并行 DAG、可靠性与恢复场景
- ``benchmarks/quality.py`` VulnTell 业务质量评测（标准化/去重/部分失败）
- ``benchmarks/reference_comparison.py`` 参考框架对比记录（等价才可比）
- ``benchmarks/cli.py``     离线 CLI，输出 JSON/CSV/Markdown

观测数据模型与记录器位于核心 ``src/magent/observability/``；本目录只消费它们。

默认不联网、不调用真实 LLM、不抓取漏洞引用 URL、不使用未授权真实漏洞数据。
所有结果写入 ``benchmarks/out/``（已被 .gitignore 忽略），不提交临时数据库与缓存。
"""

from __future__ import annotations

__all__ = ["FRAMEWORK_VERSION", "DATASET_VERSIONS"]

FRAMEWORK_VERSION = "0.1.0"

# 阶段 7 冻结的数据集/窗口/解析器/去重/指标版本（阶段 8 不得私自替换）
DATASET_VERSIONS = {
    "dataset_id": "vulntell-demo",
    "dataset_version": "2024Q1",
    "parser_version": "1",
    "deduplication_version": "1",
    "metric_version": "1",
}
