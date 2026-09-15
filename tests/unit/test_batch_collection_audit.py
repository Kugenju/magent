import asyncio
import datetime as dt
import json
from pathlib import Path

from apps.vulntell.batch.collector import collect_adapter
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


class _PagedAdapter:
    async def fetch_page(self, request, cursor):
        page = int(cursor or "0")
        rows = [
            SourceRecord(source_record_id=f"r-{page}-{i}", payload={"cve_id": f"CVE-2026-{page}{i:04d}"})
            for i in range(60)
        ]
        return SourcePage(
            source=request.source,
            records=tuple(rows),
            observed_at=request.window_end,
            has_more=page == 0,
            next_cursor="1" if page == 0 else None,
            page_index=page,
            request_fingerprint=request.request_fingerprint,
        )


def test_collector_records_pagination_without_silent_truncation(tmp_path: Path):
    request = SourceRequest(
        source="test",
        dataset_id="d",
        dataset_version="v",
        window_start=dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
        window_end=dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc),
        page_size=60,
    )

    manifest, documents = asyncio.run(collect_adapter(_PagedAdapter(), request, tmp_path))

    assert len(documents) == 120
    assert manifest.page_count == 2
    assert manifest.fetched_record_count == 120
    assert manifest.truncated is False
    assert manifest.collection_complete is True
    stored = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert stored["record_count"] == 120
