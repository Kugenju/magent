"""VulnTell 业务 Graph 组装（阶段 3 从 examples.vulntell.graph 迁移，阶段 5 扩展）。

拓扑：dispatch → 并行采集 NVD/CNVD/CISA KEV → 各自标准化 → join 去重 → 持久化 →
评估 → 报告。持久化节点通过阶段 6 的 side-effect 工具 + SideEffectSink 保证重放
幂等。采集分支失败降级为部分失败，不触发框架 fail_fast。

Graph 自身不含业务库连接或 provider 细节；store 通过依赖注入传入，仅在 persist
工具的闭包中使用。与阶段 0 baseline 的 Graph 拓扑/节点名完全一致。

阶段 5 扩展：支持 live 模式，可选择性启用 NVD/CISA KEV 真实 adapter。
"""

from __future__ import annotations

import pathlib
from typing import Optional

from magent import AgentResult, BaseAgent, CompiledGraph, END, GraphBuilder
from magent.llm import LLMProvider
from magent.tools import ToolRegistry, tool
from pydantic import BaseModel

from apps.vulntell.domain.models import CanonicalVulnerability, SourceObservation
from apps.vulntell.pipeline.agents import (
    CollectAgent,
    DedupeAgent,
    EvaluateAgent,
    NormalizeAgent,
    PersistAgent,
    ReportAgent,
)
from apps.vulntell.sources.legacy import FaultySourceAdapter, FixtureSourceAdapter, SourceAdapter
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest
from apps.vulntell.storage.legacy import VulnTellStore

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures"


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


def _create_adapter(
    source: str,
    *,
    faulty_sources: set[str],
    fixture_dir: pathlib.Path,
    live_adapter: Optional[SourceAdapter] = None,
) -> SourceAdapter:
    """创建数据源 adapter。

    优先级：faulty > live_adapter > fixture
    """
    if source in faulty_sources:
        return FaultySourceAdapter(source)
    if live_adapter is not None:
        return live_adapter
    return FixtureSourceAdapter(str(fixture_dir / f"{source}_sample.json"), source)


def build_vulntell_graph(
    meta,
    store: VulnTellStore,
    sink,
    provider: LLMProvider | None = None,
    *,
    fixture_dir: pathlib.Path = _FIXTURE_DIR,
    faulty_sources: Optional[set[str]] = None,
    live_adapters: Optional[dict[str, SourceAdapter]] = None,
) -> "CompiledGraph":
    """构建 VulnTell 业务 Graph。

    Args:
        meta: 数据集元数据
        store: 持久化存储
        sink: SideEffectSink
        provider: LLM provider
        fixture_dir: fixture 目录
        faulty_sources: 故障注入来源集合
        live_adapters: live 模式 adapter 字典（key: source, value: adapter）
    """
    faulty_sources = faulty_sources or set()
    live_adapters = live_adapters or {}

    # 创建 adapter
    nvd_adapter = _create_adapter(
        "nvd",
        faulty_sources=faulty_sources,
        fixture_dir=fixture_dir,
        live_adapter=live_adapters.get("nvd"),
    )
    cnvd_adapter = _create_adapter(
        "cnvd",
        faulty_sources=faulty_sources,
        fixture_dir=fixture_dir,
        live_adapter=live_adapters.get("cnvd"),
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
