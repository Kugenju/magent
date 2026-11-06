import asyncio
from datetime import datetime, timezone, timedelta

from apps.vulntell.sources.paloalto import PaloAltoAdapter, PaloAltoConfig
from apps.vulntell.sources.exploitdb import ExploitDBAdapter, ExploitDBConfig
from apps.vulntell.sources.protocol import SourceRequest


def _request(source):
    end = datetime.now(timezone.utc)
    return SourceRequest(source, source, "test", end - timedelta(days=730), end, page_size=100)


def test_paloalto_rss_normalized_records():
    async def transport(**kwargs):
        return {"status_code": 200, "data": [{"id": "CVE-2026-1", "title": "CVE-2026-1 advisory",
                "published": "2026-01-01T00:00:00Z", "url": "https://security.paloaltonetworks.com/CVE-2026-1"}]}
    page = asyncio.run(PaloAltoAdapter(PaloAltoConfig(), transport).fetch_page(_request("paloalto")))
    assert page.record_count == 1
    assert page.records[0].payload["references"][0]["type"] == "advisory"


def test_exploitdb_csv_normalized_records():
    async def transport(**kwargs):
        return {"status_code": 200, "data": [{"id": "1", "description": "demo", "date_published": "2026-01-01",
                "date_updated": "2026-01-02", "codes": "CVE-2026-0001", "platform": "linux", "type": "webapps"}]}
    page = asyncio.run(ExploitDBAdapter(ExploitDBConfig(), transport).fetch_page(_request("exploitdb")))
    assert page.record_count == 1
    assert page.records[0].payload["cve_id"] == "CVE-2026-0001"
