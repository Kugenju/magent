"""阶段 7 — 去重 / 聚合测试。"""

from __future__ import annotations

import pathlib

from examples.vulntell.dedupe import deduplicate
from examples.vulntell.loading import load_dataset_meta, load_fixture
from examples.vulntell.normalize import normalize_record

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples" / "vulntell" / "fixtures"
_OBSERVED = __import__("datetime").datetime(2023, 12, 31, 23, 59, 59, tzinfo=__import__("datetime").timezone.utc)


def _observations():
    out = []
    for f in ("nvd_sample.json", "cnvd_sample.json"):
        for raw in load_fixture(_FIXTURE_DIR / f, observed_at=_OBSERVED):
            obs, _ = normalize_record(raw)
            out.append(obs)
    return out


def test_shared_cve_merges_across_sources():
    canonical, pending = deduplicate(_observations())
    merged = next(c for c in canonical if c.cve_id == "CVE-2023-1004")
    assert set(merged.sources) == {"nvd", "cnvd"}
    assert merged.observation_count == 2


def test_no_cve_record_goes_to_pending():
    canonical, pending = deduplicate(_observations())
    assert len(pending) == 1
    assert pending[0].source_record_id == "CNVD-NO-CVE"
    # canonical 不含无 cve 的记录
    assert all(c.cve_id for c in canonical)


def test_canonical_count_is_unique_cves():
    canonical, _ = deduplicate(_observations())
    # NVD 4 个 + CNVD 新增 1005（1004 共享）= 5
    assert len(canonical) == 5


def test_field_conflict_uses_declared_priority():
    canonical, _ = deduplicate(_observations())
    merged = next(c for c in canonical if c.cve_id == "CVE-2023-1004")
    # nvd 优先级高于 cnvd（SOURCE_PRIORITY）
    assert merged.title == "Shared CVE with CNVD"
    # 引用合并去重
    assert len(merged.references) == 2


def test_dedupe_is_deterministic():
    a, _ = deduplicate(_observations())
    b, _ = deduplicate(_observations())
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]
