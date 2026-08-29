"""阶段 7 — 确定性标准化与质量问题测试。"""

from __future__ import annotations

import datetime as dt
import pathlib

from examples.vulntell.loading import load_fixture
from examples.vulntell.models import QualityIssue
from examples.vulntell.normalize import normalize_record

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples" / "vulntell" / "fixtures"
_OBSERVED = dt.datetime(2023, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)


def _nvd(rec_id):
    recs = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)
    return next(r for r in recs if r.record_id == rec_id)


def _issues(obs):
    return {(i.field, i.issue_type) for i in obs.quality_issues}


def test_valid_record_has_no_quality_issues():
    obs, issues = normalize_record(_nvd("NVD-1"))
    assert obs.cve_id == "CVE-2023-1001"
    assert obs.published_at is not None
    assert obs.normalized_fields["cvss"]["score"] == 6.1
    assert issues == []


def test_missing_cvss_block_produces_missing_issue():
    obs, _ = normalize_record(_nvd("NVD-2"))
    assert ("cvss", "missing") in _issues(obs)
    assert ("description", "missing") in _issues(obs)


def test_cvss_score_missing_while_version_present():
    raw = _nvd("NVD-1")
    raw.payload = {k: v for k, v in raw.payload.items() if k != "cvss_score"}
    obs, _ = normalize_record(raw)
    assert ("cvss_score", "missing") in _issues(obs)
    assert obs.normalized_fields["cvss"]["score"] is None


def test_invalid_date_produces_invalid_issue():
    obs, _ = normalize_record(_nvd("NVD-3"))
    assert ("published_at", "invalid") in _issues(obs)
    assert obs.published_at is None  # 不可解析时间为 None，不掩盖


def test_invalid_cve_format_flagged_not_missing():
    # 构造一条 cve_id 格式非法的记录
    raw = _nvd("NVD-1")
    raw.payload = dict(raw.payload, cve_id="NOT-A-CVE")
    obs, _ = normalize_record(raw)
    assert obs.cve_id is None
    assert ("cve_id", "invalid") in _issues(obs)


def test_missing_cve_is_allowed_pending_not_flagged():
    raw = _nvd("NVD-1")
    raw.payload = {k: v for k, v in raw.payload.items() if k != "cve_id"}
    obs, _ = normalize_record(raw)
    assert obs.cve_id is None
    assert ("cve_id", "missing") not in _issues(obs)  # 无 CVE 允许，进入待匹配


def test_cwe_and_reference_validation():
    raw = _nvd("NVD-1")
    raw.payload = dict(raw.payload, cwe=["CWE-79", "bad-cwe"], references=[{"url": "ftp://x"}])
    obs, _ = normalize_record(raw)
    assert ("cwe", "invalid") in _issues(obs)
    assert ("references", "invalid") in _issues(obs)


def test_normalization_is_deterministic():
    a, ia = normalize_record(_nvd("NVD-3"))
    b, ib = normalize_record(_nvd("NVD-3"))
    assert a.model_dump() == b.model_dump()
    assert [i.model_dump() for i in ia] == [i.model_dump() for i in ib]


def test_quality_issue_carries_rule_version():
    obs, issues = normalize_record(_nvd("NVD-2"))
    assert all(isinstance(i, QualityIssue) for i in issues)
    assert all(i.rule_version for i in issues)
