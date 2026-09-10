from __future__ import annotations

from apps.vulntell.sources.msrc import MSRCAdapter


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

