"""阶段 7 — 确定性指标与报告测试。"""

from __future__ import annotations

import datetime as dt
import pathlib

from examples.vulntell.dedupe import deduplicate
from examples.vulntell.loading import load_dataset_meta, load_fixture
from examples.vulntell.metrics import compute_metrics
from examples.vulntell.models import Report
from examples.vulntell.normalize import normalize_record
from examples.vulntell.report import build_report, to_markdown

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples" / "vulntell" / "fixtures"
_OBSERVED = dt.datetime(2023, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)


def _everything():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    observations = []
    for f in ("nvd_sample.json", "cnvd_sample.json"):
        for raw in load_fixture(_FIXTURE_DIR / f, observed_at=_OBSERVED):
            obs, _ = normalize_record(raw)
            observations.append(obs)
    canonical, pending = deduplicate(observations)
    quality = [qi for o in observations for qi in o.quality_issues]
    return meta, observations, canonical, pending, quality


def test_metrics_count_and_determinism():
    meta, observations, canonical, pending, quality = _everything()
    status = {"nvd": "ok", "cnvd": "ok"}
    m1 = compute_metrics(observations, canonical, pending, quality, meta, status)
    m2 = compute_metrics(observations, canonical, pending, quality, meta, status)
    assert m1.metrics == m2.metrics
    assert m1.metrics["volume"]["unique_vulnerabilities"] == 5
    assert m1.insufficient_data is False


def test_insufficient_data_when_too_few_canonical():
    meta, observations, canonical, pending, quality = _everything()
    status = {"nvd": "ok", "cnvd": "ok"}
    m = compute_metrics(observations, canonical[:1], pending, quality, meta, status)
    assert m.insufficient_data is True


def test_metrics_record_versions_and_window():
    meta, observations, canonical, pending, quality = _everything()
    m = compute_metrics(observations, canonical, pending, quality, meta, {"nvd": "ok", "cnvd": "ok"})
    assert m.dataset_id == meta.dataset_id
    assert m.window_start == meta.window_start
    assert m.parser_version == meta.parser_version
    assert m.framework_version == meta.framework_version


def test_completeness_efficiency_separated():
    meta, observations, canonical, pending, quality = _everything()
    m = compute_metrics(observations, canonical, pending, quality, meta, {"nvd": "ok", "cnvd": "ok"})
    comp = m.metrics["completeness"]
    assert "presence_rate" in comp and "efficiency_rate" in comp
    # 存在率与有效率都是 0..1
    assert 0.0 <= comp["efficiency_rate"] <= 1.0


def test_report_includes_failure_sources_and_versions():
    meta, observations, canonical, pending, quality = _everything()
    status = {"nvd": "ok", "cnvd": "failed"}
    m = compute_metrics(observations, canonical, pending, quality, meta, status)
    rep = build_report(meta, status, canonical, pending, quality, m)
    assert isinstance(rep, Report)
    assert rep.source_status == status
    assert rep.parser_version == meta.parser_version
    md = to_markdown(rep)
    assert "VulnTell" in md and "failed" in md


def test_report_supports_llm_explanation_without_mutating():
    meta, observations, canonical, pending, quality = _everything()
    m = compute_metrics(observations, canonical, pending, quality, meta, {"nvd": "ok", "cnvd": "ok"})
    rep = build_report(meta, {"nvd": "ok", "cnvd": "ok"}, canonical, pending, quality, m, llm_explanation="说明")
    before = rep.model_dump()
    # 仅附加解释，确定性字段不变
    rep2 = build_report(meta, {"nvd": "ok", "cnvd": "ok"}, canonical, pending, quality, m)
    assert rep2.metrics == before["metrics"]
    assert rep2.llm_explanation is None
