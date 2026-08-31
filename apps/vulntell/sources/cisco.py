"""VulnTell Cisco PSIRT 适配器（阶段 8，Task 8.2）。

将 Cisco PSIRT API (https://tools.cisco.com/security/center) 响应映射为 SourceRecord。
支持分页、游标、错误分类和 Cisco 产品安全公告。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 厂商专属；自动化入口需核验
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
class CiscoConfig:
    """Cisco PSIRT 配置。"""
    endpoint: str = "https://tools.cisco.com/security/center/servicesxml"
    timeout_seconds: float = 30.0
    page_size: int = 100


class CiscoAdapter:
    """Cisco PSIRT 适配器：将 Cisco API 映射为 SourceRecord 协议。

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
        config: Optional[CiscoConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or CiscoConfig()
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
                    source="cisco",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 Cisco API 参数
        params = {
            "page": page,
            "limit": min(request.page_size, self._config.page_size),
        }

        # 添加过滤条件
        if request.filters.get("cisco_id"):
            params["cisco_id"] = request.filters["cisco_id"]
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
            return SourceError.from_exception("cisco", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "cisco",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {})
            advisories = data.get("advisories", [])

            # 转换为 SourceRecord
            records = []
            for adv in advisories:
                cisco_id = adv.get("cisco_id", "")
                if not cisco_id:
                    continue

                # 提取关键字段
                title = adv.get("title", "")
                summary = adv.get("summary", "")
                published = adv.get("published")
                updated = adv.get("updated")
                severity = adv.get("severity")
                cvss_score = adv.get("cvss_score")
                cvss_vector = adv.get("cvss_vector")

                # 提取别名
                aliases = []
                if adv.get("cve_id"):
                    aliases.append(adv["cve_id"])

                # 提取受影响产品
                affected_products = adv.get("affected_products", [])
                packages = []
                for product in affected_products:
                    packages.append({
                        "product": product.get("product", ""),
                        "version": product.get("version", ""),
                    })

                # 提取引用
                references = []
                for ref in adv.get("references", []):
                    references.append({
                        "type": ref.get("type", "WEB"),
                        "url": ref.get("url", ""),
                    })

                record = SourceRecord(
                    source_record_id=cisco_id,
                    payload={
                        "id": cisco_id,
                        "title": title,
                        "summary": summary,
                        "published": published,
                        "updated": updated,
                        "severity": severity,
                        "cvss_score": cvss_score,
                        "cvss_vector": cvss_vector,
                        "aliases": aliases,
                        "packages": packages,
                        "references": references,
                    },
                    metadata={
                        "source": "cisco",
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
                source="cisco",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("cisco", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "Cisco adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class CiscoTransport:
    """Cisco PSIRT HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 Cisco API。"""
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
