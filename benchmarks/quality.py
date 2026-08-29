"""阶段 8 VulnTell 业务质量评测（Task 5）。

使用阶段 7 冻结 fixture；如增加人工标注真值，必须另设标注版本与覆盖说明。样本不足返回
``insufficient_data``，不计算无依据排名。有真值才计算 precision/recall/F1。
"""

from __future__ import annotations

import datetime as dt
import pathlib

from pydantic import BaseModel, Field

from magent import GraphExecutor
from magent.checkpoint import SideEffectSink, SqliteCheckpointStore

from examples.vulntell.db import VulnTellStore
from examples.vulntell.graph import build_vulntell_graph
from examples.vulntell.loading import load_dataset_meta
from examples.vulntell.metrics import compute_metrics
from examples.vulntell.models import (
    CanonicalVulnerability,
    DatasetMeta,
    QualityIssue,
    Report,
    SourceObservation,
)
from examples.vulntell.state import VulnTellState

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[1] / "examples" / "vulntell" / "fixtures"

# 冻结 fixture 的标注真值（仅用于演示；替换需新标注版本）
EXPECTED_CANONICAL = [
    "CVE-2023-1001",
    "CVE-2023-1002",
    "CVE-2023-1003",
    "CVE-2023-1004",
    "CVE-2023-1005",
]
SHARED_CVE = "CVE-2023-1004"


class QualityReport(BaseModel):
    """VulnTell 质量评测结果（不含排名，只报告指标与门槛）。"""

    dataset_id: str
    dataset_version: str
    sample_count: int
    insufficient_data: bool
    standardization: dict = Field(default_factory=dict)
    dedupe: dict = Field(default_factory=dict)  # precision/recall/F1，仅当有真值时
    cross_source_consistency: bool = True
    report_completeness: bool = True
    partial_failure_usable: bool = True
    metric_reproducible: bool = True
    notes: list[str] = Field(default_factory=list)


async def run_pipeline(*, faulty=(), provider=None) -> VulnTellState:
    """跑通冻结 fixture 流程，返回最终 VulnTellState（确定性、离线）。"""
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    store = VulnTellStore(":memory:")
    store.init_schema()
    sink = SideEffectSink(SqliteCheckpointStore(":memory:"), run_id="quality", node_id="persist", node_version="1")
    graph = build_vulntell_graph(meta, store, sink, provider, fixture_dir=_FIXTURE_DIR, faulty_sources=set(faulty))
    state = VulnTellState(meta=meta)
    final, _report = await GraphExecutor(graph, run_id="quality", max_concurrency=4).run(state)
    store.close()
    return final


def evaluate_vulntell_quality(
    meta: DatasetMeta,
    final_state: VulnTellState,
    *,
    faulty: tuple[str, ...] = (),
    sample_threshold: int = 2,
) -> QualityReport:
    canonical = [CanonicalVulnerability(**c) for c in final_state.canonical]
    observations: list[SourceObservation] = [
        SourceObservation(**o) for obs in final_state.observations_by_source.values() for o in obs
    ]
    quality_issues = [QualityIssue(**q) for q in final_state.quality_issues]
    source_status = final_state.source_status

    metric = compute_metrics(observations, canonical, [], quality_issues, meta, source_status)
    insufficient = len(canonical) < sample_threshold

    # 标准化：存在率与有效率
    presence = metric.metrics["completeness"]["presence_rate"]
    efficiency = metric.metrics["completeness"]["efficiency_rate"]
    standardization = {"presence_rate": presence, "efficiency_rate": efficiency}

    # 去重 precision/recall/F1（仅当有真值）
    predicted = sorted(c.cve_id for c in canonical if c.cve_id)
    expected = set(EXPECTED_CANONICAL)
    tp = [c for c in predicted if c in expected]
    precision = (len(tp) / len(predicted)) if predicted else None
    recall = (len(tp) / len(expected)) if expected else None
    f1 = (
        (2 * precision * recall / (precision + recall))
        if (precision and recall and (precision + recall) > 0)
        else None
    )
    dedupe = {"precision": precision, "recall": recall, "f1": f1, "predicted": predicted, "expected": sorted(expected)}

    # 跨源一致性：共享 CVE 在两源中的 published_at 是否一致
    cross_ok = True
    shared = [o for o in observations if o.cve_id == SHARED_CVE]
    if len({o.source for o in shared}) >= 2:
        pubs = {o.source: o.published_at for o in shared}
        cross_ok = len({p.isoformat() if p else None for p in pubs.values()}) == 1

    # 报告完整性
    rep = Report(**final_state.report) if final_state.report else None
    report_ok = bool(
        rep
        and rep.dataset_id
        and rep.metrics
        and rep.source_status
        and "canonical_count" in rep.model_dump()
    )

    # 部分失败可用性
    partial_ok = True
    if faulty:
        partial_ok = bool(rep and all(source_status.get(s) == "failed" for s in faulty) and rep.canonical_count >= 0)

    # 指标可复现性
    metric2 = compute_metrics(observations, canonical, [], quality_issues, meta, source_status)
    reproducible = metric.model_dump() == metric2.model_dump()

    notes: list[str] = []
    if insufficient:
        notes.append("sample below threshold; no ranking produced")
    if faulty:
        notes.append(f"partial failure injected for {list(faulty)}; degraded report still produced")

    return QualityReport(
        dataset_id=meta.dataset_id,
        dataset_version=meta.dataset_version,
        sample_count=len(canonical),
        insufficient_data=insufficient,
        standardization=standardization,
        dedupe=dedupe,
        cross_source_consistency=cross_ok,
        report_completeness=report_ok,
        partial_failure_usable=partial_ok,
        metric_reproducible=reproducible,
        notes=notes,
    )
