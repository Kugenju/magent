import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

from apps.vulntell.sources.cnvd_manual import CNVDManualConfig, CNVDManualFileSource
from apps.vulntell.sources.protocol import SourceRequest


def req(cursor=None):
    now = datetime.now(timezone.utc)
    return SourceRequest("cnvd", "manual", "sha", now - timedelta(days=1), now, page_size=1, cursor=cursor)


async def test_manual_json_is_paged_and_hashed(tmp_path: Path):
    p = tmp_path / "cnvd.json"
    payload = {"records": [{"cnvdId": "CNVD-1", "title": "test"}, {"cnvdId": "CNVD-2"}]}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    src = CNVDManualFileSource(CNVDManualConfig(p))
    first = await src.fetch_page(req())
    assert first.record_count == 1
    assert first.next_cursor == "1"
    second = await src.fetch_page(req(first.next_cursor), first.next_cursor)
    assert second.records[0].source_record_id == "CNVD-2"
    assert len(second.records[0].metadata["file_sha256"]) == 64


async def test_manual_missing_file_returns_structured_error(tmp_path: Path):
    src = CNVDManualFileSource(CNVDManualConfig(tmp_path / "missing.csv"))
    result = await src.fetch_page(req())
    assert result.kind.value == "not_found"


async def test_manual_csv_canonical_fields(tmp_path: Path):
    """中文表头 CSV：CVE/等级/发布日期映射为 canonical payload 字段。"""
    p = tmp_path / "cnvd.csv"
    p.write_text(
        "CNVD编号,CVE编号,漏洞名称,危害级别,发布日期\n"
        "CNVD-2025-0001,CVE-2025-1234,测试漏洞,高,2025-03-01\n"
        "CNVD-2025-0002,,无CVE漏洞,中,2025/04/15\n",
        encoding="utf-8-sig",
    )
    src = CNVDManualFileSource(CNVDManualConfig(p))
    page = await src.fetch_page(SourceRequest(
        "cnvd", "manual", "sha",
        datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc),
        page_size=100,
    ))
    assert page.record_count == 2
    r1, r2 = page.records

    assert r1.payload["cve_id"] == "CVE-2025-1234"
    assert r1.payload["aliases"] == ["CVE-2025-1234"]
    assert r1.payload["cnvd_level"] == "高"
    assert r1.payload["published_at"] == "2025-03-01"
    assert r1.payload["title"] == "测试漏洞"
    assert len(r1.payload["import_sha256"]) == 64

    assert r2.payload["cve_id"] is None
    assert r2.payload["aliases"] == []
    assert r2.payload["published_at"] == "2025-04-15"
