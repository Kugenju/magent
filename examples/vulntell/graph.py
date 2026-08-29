"""VulnTell 并发可恢复 Graph（阶段 7，Task 5）。

流程：dispatch → 并行采集 NVD/CNVD → 各自标准化 → join 去重 → 持久化 →
评估 → 报告。持久化节点通过阶段 6 的 side-effect 工具 + 阶段 5 的
``SideEffectSink`` 保证重放幂等。采集分支失败降级为部分失败，不触发 fail_fast。
"""

from __future__ import annotations

import pathlib
from typing import Optional

from magent import AgentResult, BaseAgent, END, GraphBuilder
from magent.tools import ToolRegistry, tool
from pydantic import BaseModel

from .agents import (
    CollectAgent,
    DedupeAgent,
    EvaluateAgent,
    NormalizeAgent,
    PersistAgent,
    ReportAgent,
)
from .db import VulnTellStore
from .models import CanonicalVulnerability, SourceObservation
from .sources import FaultySourceAdapter, FixtureSourceAdapter

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"


class _Dispatch(BaseAgent):
    async def run(self, state, runtime):
        return AgentResult(updates={})


class PersistInput(BaseModel):
    observations: list[dict]
    canonical: list[dict]
    pending: list[dict]


def _make_persist_tool(store: VulnTellStore):
    @tool("persist_batch", input_model=PersistInput, side_effect=True, idempotent=True)
    async def persist_batch(args: PersistInput, ctx) -> dict:
        observations = [SourceObservation(**d) for d in args.observations]
        canonical = [CanonicalVulnerability(**d) for d in args.canonical]
        pending = [SourceObservation(**d) for d in args.pending]
        for o in observations:
            store.upsert_observation(o)
        for c in canonical:
            store.upsert_canonical(c)
        for p in pending:
            store.upsert_observation(p)
        quality = [qi for o in observations for qi in o.quality_issues]
        store.insert_quality_issues(quality)
        return {"written_observations": len(observations), "written_canonical": len(canonical)}

    return persist_batch


def build_vulntell_graph(
    meta,
    store: VulnTellStore,
    sink,
    provider=None,
    *,
    fixture_dir: pathlib.Path = _FIXTURE_DIR,
    faulty_sources: Optional[set[str]] = None,
) -> "CompiledGraph":
    faulty_sources = faulty_sources or set()
    nvd_adapter = (
        FaultySourceAdapter("nvd")
        if "nvd" in faulty_sources
        else FixtureSourceAdapter(str(fixture_dir / "nvd_sample.json"), "nvd")
    )
    cnvd_adapter = (
        FaultySourceAdapter("cnvd")
        if "cnvd" in faulty_sources
        else FixtureSourceAdapter(str(fixture_dir / "cnvd_sample.json"), "cnvd")
    )

    registry = ToolRegistry(allowlist=["persist_batch"])
    registry.register(_make_persist_tool(store))

    builder = GraphBuilder()
    builder.add_node("dispatch", _Dispatch("dispatch"))
    builder.add_node("collect_nvd", CollectAgent("nvd", nvd_adapter))
    builder.add_node("collect_cnvd", CollectAgent("cnvd", cnvd_adapter))
    builder.add_node("normalize_nvd", NormalizeAgent("nvd"))
    builder.add_node("normalize_cnvd", NormalizeAgent("cnvd"))
    builder.add_node("dedupe", DedupeAgent("dedupe"))
    builder.add_node("persist", PersistAgent(registry, sink))
    builder.add_node("evaluate", EvaluateAgent("evaluate"))
    builder.add_node("report", ReportAgent(provider))

    builder.set_entry_point("dispatch")
    builder.add_parallel_edges("dispatch", ["collect_nvd", "collect_cnvd"])
    builder.add_edge("collect_nvd", "normalize_nvd")
    builder.add_edge("collect_cnvd", "normalize_cnvd")
    builder.add_edge("normalize_nvd", "dedupe")
    builder.add_edge("normalize_cnvd", "dedupe")
    builder.add_join("dedupe", ["normalize_nvd", "normalize_cnvd"])
    builder.add_edge("dedupe", "persist")
    builder.add_edge("persist", "evaluate")
    builder.add_edge("evaluate", "report")
    builder.add_edge("report", END)

    return builder.compile()
