from __future__ import annotations

from apps.vulntell.sources.msrc import MSRCAdapter
from apps.vulntell.sources.protocol import SourceRequest
from datetime import datetime, timezone
import asyncio


def test_msrc_cvrf_xml_parser_emits_cve_records_without_raw_xml():
    xml = """
    <cvrf:cvrfdoc xmlns:cvrf="urn:test" xmlns:vuln="urn:vuln">
      <cvrf:DocumentTracking>
        <cvrf:InitialReleaseDate>2026-09-08T07:00:00Z</cvrf:InitialReleaseDate>
      </cvrf:DocumentTracking>
      <vuln:Vulnerability>
        <vuln:Title>Example vulnerability</vuln:Title>
        <vuln:CVE>CVE-2026-12345</vuln:CVE>
      </vuln:Vulnerability>
    </cvrf:cvrfdoc>
    """
    data = MSRCAdapter._parse_cvrf_xml(xml)
    assert data["total"] == 1
    record = data["value"][0]
    assert record["id"] == "CVE-2026-12345"
    assert record["documentTitle"] == "Example vulnerability"
    assert "<cvrf" not in str(record)


def test_msrc_expanded_snapshot_is_not_paginated_again():
    class Transport:
        async def __call__(self, **kwargs):
            return {"status_code": 200, "data": {
                "value": [{"id": "CVE-2026-12345", "alias": "CVE-2026-12345",
                           "documentTitle": "Example", "releaseDate": "2026-09-08T00:00:00Z",
                           "cve_id": "CVE-2026-12345"}],
                "total": 1, "cvrf_expanded": True,
            }}

    request = SourceRequest(
        source="msrc", dataset_id="msrc-cve", dataset_version="test",
        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2027, 1, 1, tzinfo=timezone.utc), page_size=100,
    )
    page = asyncio.run(MSRCAdapter(transport=Transport()).fetch_page(request))
    assert not page.has_more
    assert page.next_cursor is None
