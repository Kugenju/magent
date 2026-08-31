"""VulnTell 新入口（阶段 1，Task 1.3，阶段 5 扩展）。

``python -m apps.vulntell`` 可运行。参数语义与旧入口一致；输出格式（Markdown +
``--json`` 报告块 + 可选 trace 写出）沿用当前实现，避免在迁移阶段改变报告 schema。

退出码：成功 0，运行失败 1，KeyboardInterrupt 130。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from apps.vulntell.domain.models import Report
from apps.vulntell.reporting.exporters import to_markdown

from .application import VulnTellApplication
from .config import VulnTellConfig


def _write_trace(config: VulnTellConfig, result) -> None:
    assert config.trace_prefix is not None
    prefix = config.trace_prefix
    from magent.checkpoint.models import state_schema_hash
    from magent.observability import build_observability, write_json, write_jsonl

    schema_hash = state_schema_hash(type(result.final_state))
    trace, spans, summary = build_observability(
        result.execution_report,
        workflow_id="graph",
        workflow_version="1",
        state_schema_version=schema_hash,
    )
    prefix = config.trace_prefix
    write_jsonl(prefix + ".jsonl", [trace, *spans])
    write_json(prefix + ".summary.json", summary)
    print(f"[observability] wrote {prefix}.jsonl ({len(spans)} spans) + summary")


def main() -> int:
    parser = argparse.ArgumentParser(description="VulnTell offline vertical example")
    parser.add_argument("--db", default=":memory:")
    parser.add_argument("--checkpoint", default=":memory:")
    parser.add_argument("--run-id", default="vulntell-demo-run")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-llm", action="store_true", help="禁用可选 LLM 解释")
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument("--faulty", nargs="*", default=[], help="注入故障的来源名，如 nvd cnvd")
    parser.add_argument("--trace", default=None, help="可选：写出 Trace/Span 观测 JSONL 与此路径前缀")
    # Live 模式参数
    parser.add_argument("--live", action="store_true", help="启用 live 模式（需要网络）")
    parser.add_argument("--source", choices=["nvd", "cisa_kev", "cnvd"], help="live 模式数据源")
    parser.add_argument("--window-days", type=int, default=30, help="回溯天数（默认 30）")
    args = parser.parse_args()

    config = VulnTellConfig.from_cli_args(
        db=args.db,
        checkpoint=args.checkpoint,
        run_id=args.run_id,
        resume=args.resume,
        no_llm=args.no_llm,
        json_output=args.json_output,
        faulty=args.faulty,
        trace=args.trace,
        live=args.live,
        source=args.source,
        window_days=args.window_days,
    )

    app = VulnTellApplication(config)
    result = asyncio.run(app.run())

    if result.report:
        rep = result.report
        print(to_markdown(rep))
        if config.json_output:
            print("\n--- JSON ---")
            print(rep.model_dump_json(indent=2))
    else:
        print("no report produced; success =", result.execution_report.success)

    if config.trace_prefix:
        _write_trace(config, result)

    return 0 if result.execution_report.success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
