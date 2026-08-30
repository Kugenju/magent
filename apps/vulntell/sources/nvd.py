"""VulnTell NVD 适配器（阶段 5，Task 5.1）。

将 NVD API (https://services.nvd.nist.gov/rest/json/cves/2.0) 响应映射为 SourceRecord。
支持分页、游标、429 限流、超时和错误分类。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind, classify_http_status
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


@dataclass
class NVDConfig:
    """NVD API 配置。"""
    endpoint: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    page_size: int = 2000  # NVD 最大 page size
    timeout_seconds: float = 30.0
    api_key: Optional[str] = None  # 可选 API key 提高速率限制


class NVDAdapter:
    """NVD 适配器：将 NVD CVE API 映射为 SourceRecord 协议。

    支持：
    - 分页：使用 startIndex 和 resultsPerPage
    - 游标：格式 "{startIndex}"，整数偏移
    - 窗口：lastModStartDate/lastModEndDate（半开区间 [start, end)）
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    """

    def __init__(
        self,
        config: Optional[NVDConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or NVDConfig()
        self._transport = transport or self._default_transport

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（格式 "{startIndex}"）

        Returns:
            SourcePage 或 SourceError
        """
        # 解析游标
        start_index = 0
        if cursor:
            try:
                start_index = int(cursor)
            except ValueError:
                return SourceError(
                    source="nvd",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 NVD API 参数
        params = {
            "startIndex": start_index,
            "resultsPerPage": min(request.page_size, self._config.page_size),
            "lastModStartDate": request.window_start.isoformat(),
            "lastModEndDate": request.window_end.isoformat(),
        }

        # 添加过滤条件
        if request.filters.get("cve_id"):
            params["cveId"] = request.filters["cve_id"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                params=params,
                api_key=self._config.api_key,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("nvd", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            error = SourceError.from_http_status(
                "nvd",
                status_code,
                response.get("error", ""),
            )
            return error

        # 解析响应
        try:
            data = response.get("data", {})
            vulnerabilities = data.get("vulnerabilities", [])
            total_results = data.get("totalResults", 0)

            # 转换为 SourceRecord
            records = []
            for vuln in vulnerabilities:
                cve = vuln.get("cve", {})
                record_id = cve.get("id", "")
                if not record_id:
                    continue

                # 提取关键字段（不保存完整 payload）
                record = SourceRecord(
                    source_record_id=record_id,
                    payload={
                        "id": record_id,
                        "published": cve.get("published"),
                        "lastModified": cve.get("lastModified"),
                        "descriptions": [
                            d for d in cve.get("descriptions", [])
                            if d.get("lang") == "en"
                        ][:1],  # 只保留英文描述
                    },
                    metadata={
                        "source": "nvd",
                        "published_at": cve.get("published"),
                        "modified_at": cve.get("lastModified"),
                    },
                )
                records.append(record)

            # 计算是否有更多页
            next_index = start_index + len(records)
            has_more = next_index < total_results
            next_cursor = str(next_index) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=start_index // request.page_size,
                source="nvd",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("nvd", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        api_key: Optional[str],
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "NVD adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class NVDTransport:
    """NVD HTTP transport（使用 httpx）。"""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        api_key: Optional[str],
        timeout: float,
    ) -> dict:
        """调用 NVD API。"""
        import httpx

        headers = {}
        if api_key:
            headers["apiKey"] = api_key

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    endpoint,
                    params=params,
                    headers=headers,
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
