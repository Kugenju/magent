"""VulnTell 离线 CLI（阶段 7，Task 8）。

默认只使用 fixture，从不联网、不需要 API Key、不执行漏洞利用或外部命令。
用法::

    python -m examples.vulntell
    python -m examples.vulntell --checkpoint run.db --resume
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import pathlib
import sys

from magent import GraphExecutor
from magent.checkpoint import SqliteCheckpointStore, SideEffectSink
from magent.llm import FakeProvider

from .db import VulnTellStore
from .graph import build_vulntell_graph
from .loading import load_dataset_meta
from .models import Report, utc
from .report import to_markdown
from .state import VulnTellState

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"


async def run_once(args) -> int:
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = VulnTellStore(args.db)
    store.init_schema()
    checkpoint_store = SqliteCheckpointStore(args.checkpoint)
    sink = SideEffectSink(checkpoint_store, run_id=args.run_id, node_id="persist", node_version="1")
    provider = FakeProvider() if not args.no_llm else None

    graph = build_vulntell_graph(
        meta, store, sink, provider, fixture_dir=_FIXTURE_DIR, faulty_sources=set(args.faulty)
    )
    state = VulnTellState(meta=meta)

    executor = GraphExecutor(
        graph, run_id=args.run_id, max_concurrency=4, checkpoint_store=checkpoint_store
    )
    if args.resume:
        final_state, report = await executor.resume(args.run_id, state)
    else:
        final_state, report = await executor.run(state)

    if final_state.report:
        rep = Report(**final_state.report)
        print(to_markdown(rep))
        if args.json:
            print("\n--- JSON ---")
            print(rep.model_dump_json(indent=2))
    else:
        print("no report produced; success =", report.success)

    if args.trace:
        from magent.checkpoint.models import state_schema_hash
        from magent.observability import build_observability, write_json, write_jsonl

        schema_hash = state_schema_hash(VulnTellState)
        trace, spans, summary = build_observability(
            report, workflow_id="graph", workflow_version="1", state_schema_version=schema_hash
        )
        write_jsonl(args.trace + ".jsonl", [trace, *spans])
        write_json(args.trace + ".summary.json", summary)
        print(f"[observability] wrote {args.trace}.jsonl ({len(spans)} spans) + summary")

    store.close()
    return 0 if report.success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="VulnTell offline vertical example")
    parser.add_argument("--db", default=":memory:")
    parser.add_argument("--checkpoint", default=":memory:")
    parser.add_argument("--run-id", default="vulntell-demo-run")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-llm", action="store_true", help="禁用可选 LLM 解释")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--faulty", nargs="*", default=[], help="注入故障的来源名，如 nvd cnvd")
    parser.add_argument("--trace", default=None, help="可选：写出 Trace/Span 观测 JSONL 与此路径前缀")
    args = parser.parse_args()
    try:
        return asyncio.run(run_once(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
