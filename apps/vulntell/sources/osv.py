"""VulnTell OSV.dev 适配器（阶段 6，Task 6.1）。

将 OSV.dev API (https://osv.dev) 响应映射为 SourceRecord。
支持分页、游标、错误分类和批量查询。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 生态以开源包为主；需统一 ecosystem
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
class OSVConfig:
    """OSV.dev 配置。"""
    endpoint: str = "https://osv.dev"
    # Public API endpoint; requires POST querybatch payload.
    batch_endpoint: str = "https://api.osv.dev/v1/querybatch"
    timeout_seconds: float = 30.0
    page_size: int = 100  # OSV 每页记录数


# OSV 生态映射
OSV_ECOSYSTEMS = {
    "npm": "npm",
    "pypi": "PyPI",
    "maven": "Maven",
    "go": "Go",
    "crates.io": "crates.io",
    "nuget": "NuGet",
    "rubygems": "RubyGems",
    "packagist": "Packagist",
    "pub": "Pub",
    "conan": "Conan",
    "github-action": "GitHub Action",
}


class OSVAdapter:
    """OSV.dev 适配器：将 OSV API 映射为 SourceRecord 协议。

    支持：
    - 分页：使用 page_token
    - 游标：格式 "{page_token}"
    - 批量查询：支持多包联合查询
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    """

    def __init__(
        self,
        config: Optional[OSVConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or OSVConfig()
        self._transport = transport or self._default_transport

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（格式 "{page_token}"）

        Returns:
            SourcePage 或 SourceError
        """
        # 解析游标
        page_token = None
        if cursor:
            page_token = cursor

        # 构建 OSV API 参数
        params = {
            "page_token": page_token,
            "page_size": min(request.page_size, self._config.page_size),
        }

        # 添加过滤条件
        if request.filters.get("ecosystem"):
            params["ecosystem"] = request.filters["ecosystem"]
        if request.filters.get("package"):
            params["package"] = request.filters["package"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.batch_endpoint,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("osv", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "osv",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {}) or {}
            # OSV querybatch responses wrap results per package; flatten them
            # so callers always consume a uniform ``vulns`` list.  This also
            # supports live transports that query /v1/querybatch directly.
            vulns = data.get("vulns", [])
            if not vulns and data.get("results"):
                vulns = []
                for result in data.get("results", []):
                    vulns.extend(result.get("vulns", []) or [])
            next_page_token = data.get("next_page_token")

            # 转换为 SourceRecord
            records = []
            for vuln in vulns:
                vuln_id = vuln.get("id", "")
                if not vuln_id:
                    continue

                # 提取关键字段
                summary = vuln.get("summary", "")
                details = vuln.get("details", "")
                published = vuln.get("published")
                modified = vuln.get("modified", published)

                # 提取受影响包信息
                affected = vuln.get("affected", [])
                packages = []
                for aff in affected:
                    pkg = aff.get("package", {})
                    ecosystem = pkg.get("ecosystem", "")
                    name = pkg.get("name", "")
                    if ecosystem and name:
                        packages.append({
                            "ecosystem": ecosystem,
                            "name": name,
                        })

                # 提取严重性
                severity = vuln.get("severity", [])

                # 提取别名
                aliases = vuln.get("aliases", [])

                # 提取引用
                references = []
                for ref in vuln.get("references", []):
                    references.append({
                        "type": ref.get("type", "WEB"),
                        "url": ref.get("url", ""),
                    })

                # 提取版本范围
                version_ranges = []
                for aff in affected:
                    ranges = aff.get("ranges", [])
                    for r in ranges:
                        events = r.get("events", [])
                        version_ranges.append({
                            "type": r.get("type", ""),
                            "events": events,
                        })

                record = SourceRecord(
                    source_record_id=vuln_id,
                    payload={
                        "id": vuln_id,
                        "summary": summary,
                        "details": details,
                        "published": published,
                        "modified": modified,
                        "aliases": aliases,
                        "packages": packages,
                        "severity": severity,
                        "references": references,
                        "version_ranges": version_ranges,
                    },
                    metadata={
                        "source": "osv",
                        "published_at": published,
                        "modified_at": modified,
                    },
                )
                records.append(record)

            # 计算是否有更多页
            has_more = next_page_token is not None
            next_cursor = next_page_token if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=0,
                source="osv",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("osv", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "OSV adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class OSVTransport:
    """OSV.dev HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 OSV API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient() as client:
            try:
                # The public OSV API exposes querybatch as POST.  For
                # compatibility with the adapter's paging contract, callers
                # may provide ``queries`` in params; otherwise retain GET for
                # list-style mirrors/fixtures.
                if endpoint.rstrip('/').endswith(('querybatch', 'querybatch/')):
                    queries = params.pop("queries", [])
                    if not queries and params.get("package"):
                        queries = [{"package": {"ecosystem": params.get("ecosystem", "PyPI"), "name": params["package"]}}]
                    response = await client.post(endpoint, json={"queries": queries}, timeout=timeout)
                else:
                    response = await client.get(endpoint, params=params, timeout=timeout)
                return {
                    "status_code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None,
                    "error": response.text if response.status_code != 200 else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 408, "error": "Request timed out"}
            except httpx.RequestError as exc:
                return {"status_code": 500, "error": str(exc)}
