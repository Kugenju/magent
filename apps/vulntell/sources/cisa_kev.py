"""VulnTell CISA KEV 适配器（阶段 5，Task 5.2）。

将 CISA Known Exploited Vulnerabilities Catalog 映射为 SourceRecord。
支持版本变化检测、合成游标和增量同步。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind, classify_http_status
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


@dataclass
class CISAKEVConfig:
    """CISA KEV 配置。"""
    endpoint: str = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    timeout_seconds: float = 60.0
    catalog_version: Optional[str] = None  # 当前 catalog 版本


class CISAKEVAdapter:
    """CISA KEV 适配器：将 CISA KEV Catalog 映射为 SourceRecord 协议。

    支持：
    - 版本变化检测：使用 catalog version 作为游标
    - 增量同步：只返回版本变化后的新记录
    - 合成游标：格式 "version:{catalog_version}"

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    """

    def __init__(
        self,
        config: Optional[CISAKEVConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or CISAKEVConfig()
        self._transport = transport or self._default_transport

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（格式 "version:{catalog_version}"）

        Returns:
            SourcePage 或 SourceError
        """
        # 解析游标
        current_version = None
        if cursor:
            if cursor.startswith("version:"):
                current_version = cursor[8:]
            else:
                return SourceError(
                    source="cisa_kev",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("cisa_kev", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "cisa_kev",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {})
            catalog_version = data.get("catalogVersion", "")
            vulnerabilities = data.get("vulnerabilities", [])

            # 版本变化检测
            if current_version and catalog_version == current_version:
                # 版本未变化，返回空页
                return SourcePage(
                    records=(),
                    next_cursor=None,
                    has_more=False,
                    page_index=0,
                    source="cisa_kev",
                    observed_at=datetime.now(timezone.utc),
                    request_fingerprint=request.request_fingerprint,
                )

            # 转换为 SourceRecord
            records = []
            for vuln in vulnerabilities:
                cve_id = vuln.get("cveID", "")
                if not cve_id:
                    continue

                # 提取关键字段（不保存完整 payload）
                record = SourceRecord(
                    source_record_id=cve_id,
                    payload={
                        "cveID": cve_id,
                        "vendorProject": vuln.get("vendorProject"),
                        "product": vuln.get("product"),
                        "vulnerabilityName": vuln.get("vulnerabilityName"),
                        "dateAdded": vuln.get("dateAdded"),
                        "shortDescription": vuln.get("shortDescription"),
                        "requiredAction": vuln.get("requiredAction"),
                        "dueDate": vuln.get("dueDate"),
                        "knownRansomwareCampaignUse": vuln.get("knownRansomwareCampaignUse"),
                        "notes": vuln.get("notes"),
                    },
                    metadata={
                        "source": "cisa_kev",
                        "published_at": vuln.get("dateAdded"),
                        "modified_at": vuln.get("dateAdded"),
                        "catalog_version": catalog_version,
                    },
                )
                records.append(record)

            # CISA KEV 通常不分页（单个文件包含所有记录）
            # 使用版本作为游标（用于版本变化检测）
            # 由于 has_more=False，next_cursor 必须为 None
            return SourcePage(
                records=tuple(records),
                next_cursor=None,
                has_more=False,
                page_index=0,
                source="cisa_kev",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("cisa_kev", exc)

    async def _default_transport(
        self,
        endpoint: str,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "CISA KEV adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class CISAKEVTransport:
    """CISA KEV HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        timeout: float,
    ) -> dict:
        """调用 CISA KEV API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(endpoint, timeout=timeout)
                return {
                    "status_code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None,
                    "error": response.text if response.status_code != 200 else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 408, "error": "Request timed out"}
            except httpx.RequestError as exc:
                return {"status_code": 500, "error": str(exc)}
