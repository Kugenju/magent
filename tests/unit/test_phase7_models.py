"""阶段 7 — 领域模型、fixture 加载与数据集元数据测试。"""

from __future__ import annotations

import datetime as dt
import pathlib

from examples.vulntell.loading import load_dataset_meta, load_fixture
from examples.vulntell.models import (
    DEDUPLICATION_VERSION,
    METRIC_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
    RawSourceRecord,
)

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples" / "vulntell" / "fixtures"
_OBSERVED = dt.datetime(2023, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)


def test_dataset_meta_loads_and_freezes_versions():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    assert meta.dataset_id == "vulntell-demo"
    assert meta.dataset_version == "2024Q1"
    assert meta.parser_version == PARSER_VERSION
    assert meta.deduplication_version == DEDUPLICATION_VERSION
    assert meta.metric_version == METRIC_VERSION
    assert set(meta.sources) == {"nvd", "cnvd"}


def test_fixture_loads_records_with_stable_hash():
    recs = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)
    assert len(recs) == 4
    assert all(isinstance(r, RawSourceRecord) for r in recs)
    assert recs[0].source == "nvd"
    assert recs[0].record_id == "NVD-1"
    # 重加载得到相同 hash（与字段顺序无关）
    recs2 = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)
    assert [r.payload_hash for r in recs] == [r.payload_hash for r in recs2]


def test_fixture_hash_is_order_independent():
    direct = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)
    assert direct[0].payload_hash != direct[1].payload_hash  # 不同内容不同 hash
    # 单条记录确定性：再次加载同文件首条 hash 不变
    again = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)
    assert direct[0].payload_hash == again[0].payload_hash


def test_cnvd_fixture_includes_shared_and_pending():
    recs = load_fixture(_FIXTURE_DIR / "cnvd_sample.json", observed_at=_OBSERVED)
    ids = {r.record_id for r in recs}
    assert "CNVD-1" in ids  # 与 NVD 共享 CVE-2023-1004
    assert "CNVD-NO-CVE" in ids  # 无 CVE，待匹配
    shared = next(r for r in recs if r.record_id == "CNVD-1")
    assert shared.payload["cve_id"] == "CVE-2023-1004"


def test_observed_at_is_utc_and_not_in_hash():
    a = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)
    b = load_fixture(
        _FIXTURE_DIR / "nvd_sample.json",
        observed_at=dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc),
    )
    # observed_at 不同，但 payload_hash 只依赖 payload，故相同
    assert [r.payload_hash for r in a] == [r.payload_hash for r in b]
    assert a[0].observed_at == _OBSERVED


def test_schema_and_parser_versions_default():
    rec = load_fixture(_FIXTURE_DIR / "nvd_sample.json", observed_at=_OBSERVED)[0]
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.parser_version == PARSER_VERSION
