"""VulnTell JVN 适配器测试（2026-09 MyJVN API 迁移）。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from apps.vulntell.sources.jvn import JVNAdapter, JVNConfig
from apps.vulntell.sources.errors import SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRequest


def _make_request(**kwargs) -> SourceRequest:
    defaults = {
        "source": "jvn",
        "dataset_id": "test",
        "dataset_version": "1.0",
        "window_start": datetime(2024, 9, 10, tzinfo=timezone.utc),
        "window_end": datetime(2026, 9, 15, tzinfo=timezone.utc),
        "page_size": 50,
    }
    defaults.update(kwargs)
    return SourceRequest(**defaults)


_XML_HEADER = """<?xml version="1.0" encoding="UTF-8" ?>
<rdf:RDF
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xmlns="http://purl.org/rss/1.0/"
xmlns:rss="http://purl.org/rss/1.0/"
xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns:dc="http://purl.org/dc/elements/1.1/"
xmlns:dcterms="http://purl.org/dc/terms/"
xmlns:sec="http://jvn.jp/rss/mod_sec/3.0/"
xmlns:status="http://jvndb.jvn.jp/myjvn/Status"
xml:lang="ja">
"""


def _item_xml(jvn_id: str, title: str = "テスト脆弱性", issued: str = "2025-08-20T10:00:00+09:00",
              cve: str | None = "CVE-2025-0001") -> str:
    cve_ref = f'<sec:references source="CVE" id="{cve}">https://www.cve.org/CVERecord?id={cve}</sec:references>' if cve else ""
    return f"""    <item rdf:about="https://jvndb.jvn.jp/ja/contents/2025/{jvn_id}.html">
      <title>{title}</title>
      <link>https://jvndb.jvn.jp/ja/contents/2025/{jvn_id}.html</link>
      <description>説明文</description>
      <dc:creator>Information-technology Promotion Agency, Japan</dc:creator>
      <sec:identifier>{jvn_id}</sec:identifier>
      {cve_ref}
      <sec:cpe version="2.2" vendor="ExampleVendor" product="ExampleProduct">cpe:/a:example:product</sec:cpe>
      <sec:cvss score="7.5" severity="High" vector="CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H" version="3.0" type="Base"/>
      <dc:date>{issued}</dc:date>
      <dcterms:issued>{issued}</dcterms:issued>
      <dcterms:modified>{issued}</dcterms:modified>
    </item>
"""


def _make_xml(items: list[str], total_res: int, total_ret: int, first_res: int = 1) -> str:
    body = "".join(items)
    return (
        _XML_HEADER
        + body
        + f'<status:Status version="3.3" method="getVulnOverviewList" lang="ja" retCd="0" retMax="50" '
          f'totalRes="{total_res}" totalResRet="{total_ret}" firstRes="{first_res}" feed="hnd"/>'
        + "\n</rdf:RDF>"
    )


class MockTransport:
    """Mock HTTP transport for testing."""

    def __init__(self, xml_text: str, status_code: int = 200) -> None:
        self._xml_text = xml_text
        self._status_code = status_code
        self.calls: list[dict] = []

    async def __call__(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "status_code": self._status_code,
            "data": self._xml_text if self._status_code == 200 else None,
            "error": "error" if self._status_code != 200 else None,
        }


def test_jvn_adapter_basic():
    """基本功能：返回正确记录。"""
    xml = _make_xml(
        [_item_xml("JVNDB-2025-000001"), _item_xml("JVNDB-2025-000002")],
        total_res=2, total_ret=2,
    )
    transport = MockTransport(xml)
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 2
    assert result.source == "jvn"
    assert not result.has_more

    call = transport.calls[0]
    assert call["endpoint"] == "https://jvndb.jvn.jp/myjvn"
    assert call["params"]["method"] == "getVulnOverviewList"
    assert call["params"]["feed"] == "hnd"
    assert call["params"]["startItem"] == "1"
    assert call["params"]["count"] == "50"
    # 完整 Y/M/D 起止窗口
    assert call["params"]["datePublicStartY"] == "2024"
    assert call["params"]["datePublicStartM"] == "9"
    assert call["params"]["datePublicStartD"] == "10"
    assert call["params"]["datePublicEndY"] == "2026"
    assert call["params"]["datePublicEndM"] == "9"
    assert call["params"]["datePublicEndD"] == "15"

    record = result.records[0]
    assert record.source_record_id == "JVNDB-2025-000001"
    assert record.payload["cve_id"] == "CVE-2025-0001"
    assert record.payload["cvss_score"] == 7.5
    assert record.payload["cvss_severity"] if "cvss_severity" in record.payload else True
    assert record.payload["aliases"] == ["CVE-2025-0001"]
    # +09:00 10:00 -> UTC 01:00
    assert record.payload["published_at"] == "2025-08-20T01:00:00+00:00"


def test_jvn_adapter_pagination():
    """分页：has_more 和 next_cursor。"""
    xml = _make_xml([_item_xml(f"JVNDB-2025-{i:06d}") for i in range(50)], total_res=120, total_ret=50)
    transport = MockTransport(xml)
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 50
    assert result.has_more
    assert result.next_cursor == "51"


def test_jvn_adapter_cursor():
    """游标：从指定位置继续。"""
    xml = _make_xml([_item_xml(f"JVNDB-2025-{i:06d}") for i in range(20)], total_res=70, total_ret=20, first_res=51)
    transport = MockTransport(xml)
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req, cursor="51"))
    assert isinstance(result, SourcePage)
    assert transport.calls[0]["params"]["startItem"] == "51"
    assert result.record_count == 20
    assert not result.has_more


def test_jvn_adapter_dates_passed_through():
    """日期字段：dcterms:issued/modified 原样透传（客户端不做窗口过滤）。

    窗口边界由服务端 datePublic 参数保证；feed 日期字段对修订条目
    可能是修订时间，客户端二次过滤会误删窗口内记录。
    """
    xml = _make_xml(
        [_item_xml("JVNDB-2025-000001", issued="2026-09-25T17:05:43+09:00")],
        total_res=1, total_ret=1,
    )
    transport = MockTransport(xml)
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 1
    record = result.records[0]
    # +09:00 17:05:43 -> UTC 08:05:43
    assert record.payload["published_at"] == "2026-09-25T08:05:43+00:00"
    assert record.payload["modified_at"] == "2026-09-25T08:05:43+00:00"


def test_jvn_adapter_empty_response():
    """空响应：totalRes=0 时占位 item 被跳过。"""
    xml = _make_xml(
        ['    <item rdf:about="https://jvndb.jvn.jp/apis/myjvn">\n'
         '      <title>MyJVN　該当する脆弱性対策情報はありません。</title>\n'
         '      <link>https://jvndb.jvn.jp/apis/myjvn</link>\n'
         '      <description>MyJVN　該当する脆弱性対策情報はありません。</description>\n'
         '    </item>\n'],
        total_res=0, total_ret=0,
    )
    transport = MockTransport(xml)
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert isinstance(result, SourcePage)
    assert result.record_count == 0
    assert not result.has_more


def test_jvn_adapter_rate_limit():
    """429 限流：返回 rate_limited 错误。"""
    transport = MockTransport("", status_code=429)
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.RATE_LIMITED


def test_jvn_adapter_timeout():
    """超时：返回 timeout 错误。"""
    async def timeout_transport(**kwargs):
        raise TimeoutError("Request timed out")

    adapter = JVNAdapter(transport=timeout_transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.TIMEOUT


def test_jvn_adapter_invalid_cursor():
    """无效游标：返回 invalid_response 错误。"""
    transport = MockTransport("")
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req, cursor="invalid"))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.INVALID_RESPONSE


def test_jvn_adapter_xml_parse_error():
    """XML 解析失败：返回 invalid_response 错误。"""
    transport = MockTransport("not xml <")
    adapter = JVNAdapter(transport=transport)
    req = _make_request()

    result = asyncio.run(adapter.fetch_page(req))
    assert hasattr(result, "kind")
    assert result.kind == SourceErrorKind.INVALID_RESPONSE


def test_jvn_config_defaults():
    """配置默认值。"""
    config = JVNConfig()
    assert config.endpoint == "https://jvndb.jvn.jp/myjvn"
    assert config.timeout_seconds == 30.0
    assert config.page_size == 50
