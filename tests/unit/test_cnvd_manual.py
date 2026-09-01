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
