"""VulnTell JVN 适配器（阶段 7，Task 7.5；2026-09 迁移到最新 MyJVN 数据入口）。

将 MyJVN API (https://jvndb.jvn.jp/myjvn) 的 RDF/XML 响应映射为
SourceRecord。旧 endpoint `jvndb.jvn.jp/myjvnxmlfeed` 已返回 HTTP 404，
现使用官方 MyJVN API：

- ``GET /myjvn?method=getVulnOverviewList&feed=hnd``
- 分页：``startItem``（1 起）+ ``count``（单次上限 50）
- 日期窗口：``datePublicStartY/M/D`` + ``datePublicEndY/M/D``
  （起止必须同时给出完整 Y/M/D，否则服务端返回异常结果）

注意（实测确认）：
- MyJVN feed 中的 ``dcterms:issued``/``dcterms:modified`` 对窗口内被修订的
  旧条目会返回修订时间；窗口边界由服务端 datePublic 参数保证，客户端不做
  二次日期过滤（feed 中的日期字段不可靠，二次过滤会误删窗口内记录）。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 日文字段、更新频率不一
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest

# XML 命名空间
_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "sec": "http://jvn.jp/rss/mod_sec/3.0/",
    "status": "http://jvndb.jvn.jp/myjvn/Status",
}


@dataclass
class JVNConfig:
    """JVN 配置。"""
    endpoint: str = "https://jvndb.jvn.jp/myjvn"
    timeout_seconds: float = 30.0
    page_size: int = 50  # MyJVN 单次请求上限


def _parse_jvn_datetime(value: Optional[str]) -> Optional[str]:
    """解析 JVN 时间（ISO-8601，通常 +09:00）为 ISO-8601 UTC；失败返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            # JVN 未带时区时按 JST 处理
            from datetime import timedelta, timezone as tz
            parsed = parsed.replace(tzinfo=tz(timedelta(hours=9)))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


class JVNAdapter:
    """JVN 适配器：将 MyJVN API 映射为 SourceRecord 协议。

    支持：
    - 分页：``startItem``（1 起）；对外游标为 1 起起始条号，格式 "{startItem}"
    - 窗口：服务端完整 Y/M/D 起止过滤（feed 日期字段不可靠，见模块 docstring）
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    """

    def __init__(
        self,
        config: Optional[JVNConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or JVNConfig()
        self._transport = transport or self._default_transport

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（格式 "{startItem}"，1 起）

        Returns:
            SourcePage 或 SourceError
        """
        # 解析游标
        start_item = 1
        if cursor:
            try:
                start_item = int(cursor)
            except ValueError:
                return SourceError(
                    source="jvn",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        count = min(request.page_size, self._config.page_size)
        ws = request.window_start
        we = request.window_end
        params = {
            "method": "getVulnOverviewList",
            "feed": "hnd",
            "startItem": str(start_item),
            "count": str(count),
            "datePublicStartY": str(ws.year),
            "datePublicStartM": str(ws.month),
            "datePublicStartD": str(ws.day),
            "datePublicEndY": str(we.year),
            "datePublicEndM": str(we.month),
            "datePublicEndD": str(we.day),
        }

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("jvn", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "jvn",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            xml_text = response.get("data")
            if not isinstance(xml_text, str):
                xml_text = response.get("text", "")
            root = ET.fromstring(xml_text)

            # 读取分页状态
            status_el = root.find("status:Status", _NS)
            total_res = 0
            total_ret = 0
            if status_el is not None:
                total_res = int(status_el.get("totalRes", "0"))
                total_ret = int(status_el.get("totalResRet", "0"))

            # 转换为 SourceRecord
            records = []
            for item in root.findall("rss:item", _NS):
                identifier_el = item.find("sec:identifier", _NS)
                if identifier_el is None or not (identifier_el.text or "").strip():
                    continue
                jvn_id = identifier_el.text.strip()

                title = (item.findtext("rss:title", default="", namespaces=_NS) or "").strip()
                description = (item.findtext("rss:description", default="", namespaces=_NS) or "").strip()
                link = (item.findtext("rss:link", default="", namespaces=_NS) or "").strip()

                # 时间：dcterms:issued / dcterms:modified / dc:date
                issued_raw = item.findtext("dcterms:issued", default=None, namespaces=_NS)
                modified_raw = item.findtext("dcterms:modified", default=None, namespaces=_NS)
                if not modified_raw:
                    modified_raw = item.findtext("dc:date", default=None, namespaces=_NS)
                published = _parse_jvn_datetime(issued_raw)
                modified = _parse_jvn_datetime(modified_raw)

                # 客户端不做日期过滤：窗口由服务端 datePublic 参数保证，
                # feed 中的日期字段对修订条目不可靠（见模块 docstring）。

                # CVE 别名
                aliases = []
                cve_id = None
                for ref in item.findall("sec:references", _NS):
                    ref_id = (ref.get("id") or "").strip()
                    ref_source = (ref.get("source") or "").strip().upper()
                    if ref_source == "CVE" and ref_id.startswith("CVE-"):
                        aliases.append(ref_id)
                        if cve_id is None:
                            cve_id = ref_id

                # 受影响产品（CPE）
                packages = []
                for cpe in item.findall("sec:cpe", _NS):
                    packages.append({
                        "vendor": cpe.get("vendor", ""),
                        "product": cpe.get("product", ""),
                        "cpe": (cpe.text or "").strip(),
                    })

                # CVSS
                cvss_el = item.find("sec:cvss", _NS)
                cvss_score = None
                cvss_vector = None
                cvss_version = None
                severity = None
                if cvss_el is not None:
                    try:
                        cvss_score = float(cvss_el.get("score")) if cvss_el.get("score") else None
                    except (TypeError, ValueError):
                        cvss_score = None
                    cvss_vector = cvss_el.get("vector")
                    cvss_version = cvss_el.get("version")
                    severity = cvss_el.get("severity")

                # 引用
                references = []
                if link:
                    references.append({"type": "ADVISORY", "url": link})
                for ref in item.findall("sec:references", _NS):
                    url = (ref.text or "").strip()
                    if url:
                        references.append({"type": "WEB", "url": url})

                record = SourceRecord(
                    source_record_id=jvn_id,
                    payload={
                        "id": jvn_id,
                        "cve_id": cve_id,
                        "title": title,
                        "description": description,
                        "published_at": published,
                        "modified_at": modified,
                        "cvss_score": cvss_score,
                        "cvss_vector": cvss_vector,
                        "cvss_version": cvss_version,
                        "aliases": aliases,
                        "affected": packages,
                        "packages": packages,
                        "references": references,
                    },
                    metadata={
                        "source": "jvn",
                        "published_at": published,
                        "modified_at": modified,
                    },
                )
                records.append(record)

            # 计算是否有更多页
            fetched = start_item - 1 + total_ret
            has_more = fetched < total_res
            next_cursor = str(start_item + total_ret) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=(start_item - 1) // max(count, 1),
                source="jvn",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except ET.ParseError as exc:
            return SourceError(
                source="jvn",
                kind=SourceErrorKind.INVALID_RESPONSE,
                message=f"XML parse error: {exc}",
                retryable=False,
            )
        except Exception as exc:
            return SourceError.from_exception("jvn", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "JVN adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class JVNTransport:
    """JVN HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 MyJVN API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                response = await client.get(
                    endpoint,
                    params=params,
                    timeout=timeout,
                )
                return {
                    "status_code": response.status_code,
                    "data": response.text if response.status_code == 200 else None,
                    "error": response.text if response.status_code != 200 else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 408, "error": "Request timed out"}
            except httpx.RequestError as exc:
                return {"status_code": 500, "error": str(exc)}
