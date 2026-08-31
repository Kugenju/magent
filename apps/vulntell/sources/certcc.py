"""VulnTell CERT/CC Vulnerability Notes 适配器（阶段 8，Task 8.1）。

将 CERT/CC Vulnerability Notes API (https://www.kb.cert.org/vuls) 响应映射为 SourceRecord。
支持分页、游标、错误分类和协调披露信息。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 不保证覆盖全部 CVE；网页字段需解析
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


@dataclass
class CERTCCConfig:
    """CERT/CC Vulnerability Notes 配置。"""
    endpoint: str = "https://www.kb.cert.org/vuls/api/vulnnotes"
    timeout_seconds: float = 30.0
    page_size: int = 100


class CERTCCAdapter:
    """CERT/CC Vulnerability Notes 适配器：将 CERT/CC API 映射为 SourceRecord 协议。

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
        config: Optional[CERTCCConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or CERTCCConfig()
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
                    source="certcc",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 CERT/CC API 参数
        params = {
            "page": page,
            "limit": min(request.page_size, self._config.page_size),
        }

        # 添加过滤条件
        if request.filters.get("vuln_id"):
            params["vuln_id"] = request.filters["vuln_id"]
        if request.filters.get("cve_id"):
            params["cve"] = request.filters["cve_id"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("certcc", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "certcc",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {})
            notes = data.get("notes", [])

            # 转换为 SourceRecord
            records = []
            for note in notes:
                vuln_id = note.get("vuln_id", "")
                if not vuln_id:
                    continue

                # 提取关键字段
                title = note.get("title", "")
                description = note.get("description", "")
                published = note.get("published")
                updated = note.get("updated")
                severity = note.get("severity")

                # 提取别名
                aliases = []
                if note.get("cve_id"):
                    aliases.append(note["cve_id"])

                # 提取受影响产品
                affected_products = note.get("affected_products", [])
                packages = []
                for product in affected_products:
                    packages.append({
                        "vendor": product.get("vendor", ""),
                        "product": product.get("product", ""),
                        "version": product.get("version", ""),
                    })

                # 提取引用
                references = []
                for ref in note.get("references", []):
                    references.append({
                        "type": ref.get("type", "WEB"),
                        "url": ref.get("url", ""),
                    })

                record = SourceRecord(
                    source_record_id=vuln_id,
                    payload={
                        "id": vuln_id,
                        "title": title,
                        "description": description,
                        "published": published,
                        "updated": updated,
                        "severity": severity,
                        "aliases": aliases,
                        "packages": packages,
                        "references": references,
                    },
                    metadata={
                        "source": "certcc",
                        "published_at": published,
                        "modified_at": updated,
                    },
                )
                records.append(record)

            # 计算是否有更多页
            total = data.get("total", 0)
            has_more = page * self._config.page_size < total
            next_cursor = str(page + 1) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=page - 1,
                source="certcc",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("certcc", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "CERT/CC adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class CERTCCTransport:
    """CERT/CC Vulnerability Notes HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 CERT/CC API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    endpoint,
                    params=params,
                    timeout=timeout,
                )
                return {
                    "status_code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None,
                    "error": response.text if response.status_code != 200 else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 408, "error": "Request timed out"}
            except httpx.RequestError as exc:
                return {"status_code": 500, "error": str(exc)}
