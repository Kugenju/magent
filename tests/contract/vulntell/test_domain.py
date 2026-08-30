"""VulnTell 阶段 2 领域层 contract 测试（PHASE2_PLAN.md Task 2.5）。

直接调用 ``apps.vulntell.domain`` 与 ``apps.vulntell.reporting``，不以 CLI 替代
领域单元测试。测试覆盖：模型往返稳定、标准化/去重/指标/报告与阶段 0 冻结基线一致、
非法字段保留质量问题、跨源冲突可追踪、以及领域层无网络/框架副作用。
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from unittest import mock

from apps.vulntell import FIXTURE_DIR
from apps.vulntell.domain.dedupe import deduplicate
from apps.vulntell.domain.metrics import compute_metrics
from apps.vulntell.domain.models import (
    CanonicalVulnerability,
    DatasetMeta,
    MetricSnapshot,
    QualityIssue,
    RawSourceRecord,
    Reference,
    Report,
    SourceObservation,
    utc,
)
from apps.vulntell.domain.normalize import normalize_record
from apps.vulntell.domain.schemas import load_dataset_meta, load_fixture
from apps.vulntell.reporting.report import build_report

from helpers import normalize_report_for_compare

_BASELINE_DIR = Path(__file__).resolve().parent / "baselines"


def _load_baseline(name: str) -> dict:
    import json

    return json.loads((_BASELINE_DIR / name).read_text(encoding="utf-8"))


def _run_domain():
    meta = load_dataset_meta(FIXTURE_DIR / "dataset_meta.json")
    observed = meta.window_end
    recs = []
    recs += load_fixture(FIXTURE_DIR / "nvd_sample.json", observed_at=observed)
    recs += load_fixture(FIXTURE_DIR / "cnvd_sample.json", observed_at=observed)
    observations: list[SourceObservation] = []
    all_issues: list[QualityIssue] = []
    for r in recs:
        obs, issues = normalize_record(r)
        observations.append(obs)
        all_issues.extend(issues)
    canonical, pending = deduplicate(observations)
    metrics = compute_metrics(
        observations, canonical, pending, all_issues, meta, {"nvd": "ok", "cnvd": "ok"}
    )
    report = build_report(
        meta, {"nvd": "ok", "cnvd": "ok"}, canonical, pending, all_issues, metrics
    )
    return meta, observations, all_issues, canonical, pending, metrics, report


# ---- 模型往返稳定 ----


def test_models_round_trip_is_stable() -> None:
    meta, observations, all_issues, canonical, _pending, metrics, report = _run_domain()
    samples = [
        meta,
        observations[0],
        all_issues[0],
        canonical[0],
        metrics,
        report,
    ]
    for obj in samples:
        dumped = obj.model_dump()
        rebuilt = type(obj)(**dumped)
        assert rebuilt.model_dump() == dumped


# ---- 与阶段 0 冻结基线一致 ----


def test_normalize_matches_baseline() -> None:
    _, _, all_issues, _, _, _, _ = _run_domain()
    # 默认 fixture 下，两源标准化共产生 10 个质量问题（与 baseline_default 一致）
    assert len(all_issues) == _load_baseline("baseline_default.json")["quality_issue_count"]


def test_dedupe_matches_baseline() -> None:
    _, _, _, canonical, pending, _, _ = _run_domain()
    assert len(canonical) == _load_baseline("baseline_default.json")["canonical_count"]
    assert len(pending) == _load_baseline("baseline_default.json")["pending_count"]


def test_metrics_matches_baseline() -> None:
    _, _, all_issues, canonical, pending, metrics, _ = _run_domain()
    assert metrics.metrics == _load_baseline("baseline_default.json")["metrics"]


def test_report_matches_baseline() -> None:
    # 领域测试不调用 LLM，与 no-llm 冻结基线比较（确定性字段一致）。
    _, _, all_issues, canonical, pending, metrics, report = _run_domain()
    norm = normalize_report_for_compare(report.model_dump())
    assert norm == _load_baseline("baseline_no_llm.json")


# ---- 非法字段与跨源冲突 ----


def test_invalid_fields_keep_quality_issues() -> None:
    raw = RawSourceRecord(
        source="nvd",
        record_id="r1",
        observed_at=utc(dt.datetime(2023, 6, 1, tzinfo=dt.timezone.utc)),
        dataset_id="d",
        dataset_version="v",
        payload={"cve_id": "NOT-A-CVE", "cvss_score": "bad"},
        payload_hash="h",
    )
    _obs, issues = normalize_record(raw)
    keys = {(i.field, i.issue_type) for i in issues}
    assert ("cve_id", "invalid") in keys
    assert ("cvss_score", "invalid") in keys
    assert ("title", "missing") in keys
    assert ("description", "missing") in keys
    # 缺失与无效被区分，不以默认值掩盖
    assert not any(i.issue_type == "missing" and i.field == "cve_id" for i in issues)


def test_conflicts_are_traceable() -> None:
    base = dict(
        published_at=utc(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc)),
        observed_at=utc(dt.datetime(2023, 1, 2, tzinfo=dt.timezone.utc)),
        raw_payload_hash="h",
        parser_version="1",
    )
    nvd = SourceObservation(
        source="nvd",
        source_record_id="n1",
        cve_id="CVE-2023-0001",
        normalized_fields={"title": "t", "references": []},
        quality_issues=[QualityIssue(source="nvd", source_record_id="n1", field="title", issue_type="missing", severity="low", message="x")],
        **base,
    )
    cnvd = SourceObservation(
        source="cnvd",
        source_record_id="c1",
        cve_id="CVE-2023-0001",
        normalized_fields={"title": "CNVD title", "references": []},
        quality_issues=[QualityIssue(source="cnvd", source_record_id="c1", field="cve_id", issue_type="invalid", severity="medium", message="y")],
        **base,
    )
    canonical, pending = deduplicate([nvd, cnvd])
    assert len(canonical) == 1 and len(pending) == 0
    c = canonical[0]
    # 冲突字段按来源优先级（nvd 优先）解析，不静默覆盖
    assert c.title == "t"
    assert set(c.sources) == {"nvd", "cnvd"}
    # 两来源的质量问题都被保留，可追溯
    assert len(c.quality_issues) == 2
    assert {i.source for i in c.quality_issues} == {"nvd", "cnvd"}


# ---- 无网络 / 无框架副作用 ----


def test_domain_has_no_network_or_framework_side_effect() -> None:
    loop = asyncio.new_event_loop()
    try:
        with mock.patch("socket.socket.connect", side_effect=OSError("network blocked")):
            with mock.patch(
                "socket.create_connection", side_effect=OSError("network blocked")
            ):
                # 纯函数，无需事件循环；此处仅用于隔离 patch 作用域
                meta, _obs, _iss, canonical, _pend, _m, report = loop.run_until_complete(
                    asyncio.to_thread(_run_domain)
                )
    finally:
        loop.close()
    # 领域计算本身是纯函数，不依赖 magent 运行时
    assert report is not None
    assert isinstance(meta, DatasetMeta)
    assert len(canonical) == 5
    # 纯领域模块不应引入框架编排类型
    import apps.vulntell.domain.models as m
    import apps.vulntell.domain.normalize as nm
    import apps.vulntell.domain.dedupe as dm
    import apps.vulntell.domain.metrics as mm

    for mod in (m, nm, dm, mm):
        assert not hasattr(mod, "GraphExecutor")
        assert not hasattr(mod, "BaseAgent")
