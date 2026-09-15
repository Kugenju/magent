import datetime as dt

from apps.vulntell.domain.metrics import compute_source_metrics
from apps.vulntell.domain.models import QualityIssue, SourceObservation


def _obs(source: str, rid: str, *, title=True, description=False, payload_hash="hash"):
    return SourceObservation(
        source=source,
        source_record_id=rid,
        cve_id="CVE-2026-0001",
        observed_at=dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc),
        raw_payload_hash=payload_hash,
        normalized_fields={
            "title": "title" if title else None,
            "description": "description" if description else None,
            "cvss": None,
            "cwe": [],
            "references": [],
        },
    )


def test_source_metrics_do_not_borrow_fields_from_other_sources():
    result = compute_source_metrics([
        _obs("a", "a-1", title=True, description=False),
        _obs("b", "b-1", title=False, description=True),
    ])

    assert result["a"].normalized["presence_rate"]["title"] == 1.0
    assert result["a"].normalized["presence_rate"]["description"] == 0.0
    assert result["b"].normalized["presence_rate"]["title"] == 0.0
    assert result["b"].normalized["presence_rate"]["description"] == 1.0
    assert result["a"].denominator["observations"] == 1


def test_source_metrics_expose_evidence_and_quality_confidence():
    issue = QualityIssue(
        source="a",
        source_record_id="a-1",
        field="description",
        issue_type="missing",
    )
    result = compute_source_metrics([_obs("a", "a-1")], [issue], profile=__import__("apps.vulntell.domain.models", fromlist=["EvaluationProfile"]).EvaluationProfile(min_samples=1))
    snapshot = result["a"]

    assert snapshot.evidence.observation_ids == ["a-1"]
    assert snapshot.evidence.raw_payload_hashes == ["hash"]
    assert snapshot.evidence.quality_issue_count == 1
    assert snapshot.confidence == "medium"
    assert snapshot.status == "ok"


def test_source_metrics_marks_empty_source_insufficient():
    result = compute_source_metrics([], source_status={"empty": "ok"})

    assert result["empty"].status == "insufficient_data"
    assert result["empty"].confidence == "unknown"
    assert result["empty"].normalized["presence_rate"]["title"] is None


def test_source_metrics_include_timeliness_references_and_profile_match():
    observed = _obs("a", "a-1", description=True)
    observed.published_at = dt.datetime(2026, 8, 30, tzinfo=dt.timezone.utc)
    observed.source_added_at = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
    observed.normalized_fields["references"] = [{"url": "https://example.test/advisory", "verified": True}]
    result = compute_source_metrics(
        [observed],
        profile=__import__("apps.vulntell.domain.models", fromlist=["EvaluationProfile"]).EvaluationProfile(
            min_samples=1, keywords=["title"]
        ),
    )
    snapshot = result["a"]
    assert snapshot.raw["timeliness"]["p50_delay_days"] == 2.0
    assert snapshot.raw["verifiability"]["url_count"] == 1
    assert snapshot.normalized["verified_reference_rate"] == 1.0
    assert snapshot.normalized["adaptability_rate"] == 1.0
