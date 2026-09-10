"""VulnTell Microsoft MSRC 适配器（阶段 7，Task 7.1）。

将 Microsoft MSRC API (https://api.msrc.microsoft.com) 响应映射为 SourceRecord。
支持分页、游标、错误分类和 Microsoft 产品安全更新信息。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 微软产品范围；需处理 KB 与 CVE 关联
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


@dataclass
class MSRCConfig:
    """Microsoft MSRC 配置。"""
    endpoint: str = "https://api.msrc.microsoft.com/cvrf/v3.0/updates"
    timeout_seconds: float = 30.0
    page_size: int = 100


class MSRCAdapter:
    """Microsoft MSRC 适配器：将 MSRC API 映射为 SourceRecord 协议。

    支持：
    - 分页：使用 page 和 limit
    - 游标：格式 "{page}"
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    """

    def __init__(
        self,
        config: Optional[MSRCConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or MSRCConfig()
        self._transport = transport or self._default_transport

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（格式 "{page}"）

        Returns:
            SourcePage 或 SourceError
        """
        # 解析游标
        page = 1
        if cursor:
            try:
                page = int(cursor)
            except ValueError:
                return SourceError(
                    source="msrc",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 MSRC API 参数
        params = {
            "page": page,
            "limit": min(request.page_size, self._config.page_size),
        }

        # 添加过滤条件
        if request.filters.get("year"):
            params["year"] = request.filters["year"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("msrc", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "msrc",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {})
            if isinstance(data, str) and data.lstrip().startswith("<"):
                data = self._parse_cvrf_xml(data)
            updates = data.get("value", [])
            if isinstance(updates, dict):
                updates = [updates]

            # 转换为 SourceRecord
            records = []
            for update in updates:
                # MSRC OData uses capitalized field names in production;
                # lowercase aliases remain supported for fixtures.
                update_id = update.get("id") or update.get("ID", "")
                if not update_id:
                    continue

                # 提取关键字段
                alias = update.get("alias") or update.get("Alias", "")
                document_title = update.get("documentTitle") or update.get("DocumentTitle", "")
                release_date = (update.get("releaseDate") or update.get("CurrentReleaseDate")
                                or update.get("InitialReleaseDate"))

                # 提取严重性
                severity = update.get("severity")
                cvss_score = update.get("cvssScore")
                cvss_vector = update.get("cvssVector")

                # 提取受影响产品
                vulnerabilities = update.get("vulnerabilities", [])
                products = []
                for vuln in vulnerabilities:
                    product = vuln.get("product", {})
                    product_id = product.get("productID", "")
                    product_name = product.get("name", "")
                    if product_id:
                        products.append({
                            "product_id": product_id,
                            "name": product_name,
                        })

                # 提取引用
                references = []
                for ref in update.get("references", []):
                    references.append({
                        "type": ref.get("type", "WEB"),
                        "url": ref.get("url", ""),
                    })

                record = SourceRecord(
                    source_record_id=alias or update_id,
                    payload={
                        "id": update_id,
                        "alias": alias,
                        "document_title": document_title,
                        "release_date": release_date,
                        "severity": severity,
                        "cvss_score": cvss_score,
                        "cvss_vector": cvss_vector,
                        "products": products,
                        "references": references,
                        # Canonical fields consumed by domain normalization.
                        "cve_id": update.get("cve_id") or update.get("CVE", None),
                        "title": document_title or alias or update_id,
                        "description": document_title or alias or update_id,
                        "published_at": release_date,
                        "modified_at": release_date,
                    },
                    metadata={
                        "source": "msrc",
                        "published_at": release_date,
                        "modified_at": release_date,
                    },
                )
                if release_date:
                    try:
                        parsed_release = datetime.fromisoformat(str(release_date).replace("Z", "+00:00"))
                        if parsed_release.tzinfo is None:
                            parsed_release = parsed_release.replace(tzinfo=timezone.utc)
                        if not (request.window_start <= parsed_release.astimezone(timezone.utc) < request.window_end):
                            continue
                    except ValueError:
                        pass
                records.append(record)

            # 计算是否有更多页
            total = data.get("total", len(updates))
            # The updates index is not page-addressable after CVRF expansion;
            # records are already bounded to the selected bulletins.
            if isinstance(data, dict) and data.get("cvrf_expanded"):
                updates = updates[: request.page_size]
                total = len(updates)
                page = 1
            has_more = page * self._config.page_size < total
            next_cursor = str(page + 1) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=page - 1,
                source="msrc",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("msrc", exc)

    @staticmethod
    def _parse_cvrf_xml(xml_text: str) -> dict:
        """Parse official MSRC CVRF XML into compact CVE records."""
        root = ET.fromstring(xml_text)

        def local(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        def first_text(node, names: set[str]) -> str | None:
            for child in node.iter():
                if local(child.tag) in names and child.text:
                    return child.text.strip()
            return None

        release = first_text(root, {"InitialReleaseDate", "CurrentReleaseDate"})
        rows = []
        for vuln in (n for n in root.iter() if local(n.tag) == "Vulnerability"):
            cve = first_text(vuln, {"CVE"})
            if not cve or not re.fullmatch(r"CVE-\d{4}-\d{4,}", cve):
                continue
            title = first_text(vuln, {"Title", "Notes"}) or cve
            rows.append({
                "id": cve,
                "alias": cve,
                "documentTitle": title,
                "releaseDate": release,
                "cve_id": cve,
                "references": [],
                "vulnerabilities": [],
            })
        return {"value": rows, "total": len(rows)}

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "MSRC adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class MSRCTransport:
    """Microsoft MSRC HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 MSRC API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient() as client:
            try:
                if endpoint.rstrip("/").endswith("/updates"):
                    # The updates collection is only an index.  Follow the
                    # two most recent bulletins; the adapter's window filter
                    # will discard records outside the requested interval.
                    index = await client.get(endpoint, timeout=timeout)
                    if index.status_code != 200:
                        return {"status_code": index.status_code, "error": index.text}
                    updates = index.json().get("value", [])
                    updates = sorted(
                        updates,
                        key=lambda item: item.get("CurrentReleaseDate") or item.get("InitialReleaseDate") or "",
                        reverse=True,
                    )[:2]
                    rows = []
                    for update in updates:
                        url = update.get("CvrfUrl")
                        if not url:
                            continue
                        bulletin = await client.get(url, timeout=timeout)
                        if bulletin.status_code != 200:
                            continue
                        parsed = MSRCAdapter._parse_cvrf_xml(bulletin.text)
                        rows.extend(parsed.get("value", []))
                    return {"status_code": 200, "data": {"value": rows, "total": len(rows), "cvrf_expanded": True}}
                response = await client.get(
                    endpoint,
                    params=params,
                    timeout=timeout,
                )
                content_type = response.headers.get("content-type", "")
                if "xml" in content_type or response.text.lstrip().startswith("<"):
                    data = response.text
                else:
                    data = response.json() if response.status_code == 200 else None
                return {
                    "status_code": response.status_code,
                    "data": data,
                    "error": response.text if response.status_code != 200 else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 408, "error": "Request timed out"}
            except httpx.RequestError as exc:
                return {"status_code": 500, "error": str(exc)}
