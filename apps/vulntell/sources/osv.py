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
import io
import zipfile
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
    # Prefer the official bulk snapshots for historical collection.  The
    # querybatch API requires package names and is not a vulnerability-feed
    # pagination endpoint.
    use_bulk: bool = False
    bulk_base_url: str = "https://osv-vulnerabilities.storage.googleapis.com"
    bulk_ecosystems: tuple[str, ...] = ("PyPI", "npm", "Go", "Maven", "crates.io")


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
        if self._config.use_bulk:
            return await self._fetch_bulk_page(request, cursor)

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
        if request.filters.get("packages"):
            params["packages"] = request.filters["packages"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.batch_endpoint,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("osv", exc)

        if response.get("status_code", 200) != 200:
            return SourceError.from_http_status("osv", response.get("status_code", 500), response.get("error", ""))
        try:
            data = response.get("data", {}) or {}
            vulns = data.get("vulns", [])
            if not vulns and data.get("results"):
                vulns = [v for result in data.get("results", []) for v in (result.get("vulns", []) or [])]
            records = [self._vuln_to_record(v) for v in vulns if v.get("id")]
            windowed = []
            for record in records:
                stamp = record.metadata.get("modified_at") or record.metadata.get("published_at")
                if stamp:
                    try:
                        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
                        if not (request.window_start <= parsed.astimezone(timezone.utc) < request.window_end): continue
                    except ValueError: pass
                windowed.append(record)
            token = data.get("next_page_token")
            return SourcePage(records=tuple(windowed), next_cursor=token, has_more=token is not None,
                              page_index=0, source="osv", observed_at=datetime.now(timezone.utc),
                              request_fingerprint=request.request_fingerprint)
        except Exception as exc:
            return SourceError.from_exception("osv", exc)

    async def _fetch_bulk_page(self, request: SourceRequest, cursor: Optional[str]) -> SourcePage | SourceError:
        """Read official OSV ecosystem ``all.zip`` snapshots.

        Snapshots are immutable and contain one JSON advisory per zip member;
        they provide a reproducible full-feed alternative to querybatch.
        Cursor is ``<ecosystem-index>:<offset>`` and therefore remains
        checkpointable by the generic collector.
        """
        try:
            ec_idx, offset = (0, 0)
            if cursor:
                parts = cursor.split(":", 1)
                ec_idx, offset = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if ec_idx >= len(self._config.bulk_ecosystems):
                return SourcePage(records=(), next_cursor=None, has_more=False,
                                  page_index=ec_idx, source="osv",
                                  observed_at=datetime.now(timezone.utc),
                                  request_fingerprint=request.request_fingerprint)
            ecosystem = self._config.bulk_ecosystems[ec_idx]
            cache_key = ecosystem
            if not hasattr(self, "_bulk_cache"):
                self._bulk_cache = {}
            records = self._bulk_cache.get(cache_key)
            if records is None:
                endpoint = f"{self._config.bulk_base_url.rstrip('/')}/{ecosystem}/all.zip"
                response = await self._transport(endpoint=endpoint, params={}, timeout=self._config.timeout_seconds)
                if response.get("status_code", 500) != 200:
                    return SourceError.from_http_status("osv", response.get("status_code", 500), response.get("error", ""))
                blob = response.get("content")
                if not blob:
                    return SourceError.from_exception("osv", ValueError("bulk snapshot response missing content"))
                parsed = []
                with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                    for name in archive.namelist():
                        if not name.endswith(".json"):
                            continue
                        try:
                            vuln = json.loads(archive.read(name))
                        except Exception:
                            continue
                        stamp = vuln.get("modified") or vuln.get("published")
                        if stamp:
                            try:
                                dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                                if not (request.window_start <= dt.astimezone(timezone.utc) < request.window_end):
                                    continue
                            except ValueError:
                                pass
                        vid = vuln.get("id")
                        if not vid: continue
                        parsed.append(self._vuln_to_record(vuln))
                records = tuple(parsed)
                self._bulk_cache[cache_key] = records
            size = min(request.page_size, self._config.page_size)
            page = records[offset:offset + size]
            new_offset = offset + len(page)
            if new_offset < len(records):
                next_cursor = f"{ec_idx}:{new_offset}"
            elif ec_idx + 1 < len(self._config.bulk_ecosystems):
                next_cursor = f"{ec_idx + 1}:0"
            else:
                next_cursor = None
            return SourcePage(records=tuple(page), next_cursor=next_cursor, has_more=next_cursor is not None,
                              page_index=ec_idx, source="osv", observed_at=datetime.now(timezone.utc),
                              request_fingerprint=request.request_fingerprint)
        except Exception as exc:
            return SourceError.from_exception("osv", exc)

    def _vuln_to_record(self, vuln: dict[str, Any]) -> SourceRecord:
        aliases = vuln.get("aliases", []) or []
        published, modified = vuln.get("published"), vuln.get("modified", vuln.get("published"))
        packages = []
        for aff in vuln.get("affected", []) or []:
            pkg = aff.get("package", {}) or {}
            if pkg.get("ecosystem") and pkg.get("name"):
                packages.append({"ecosystem": pkg["ecosystem"], "name": pkg["name"]})
        refs = [{"type": r.get("type", "WEB"), "url": r.get("url", "")} for r in vuln.get("references", []) or []]
        return SourceRecord(source_record_id=vuln["id"], payload={"id": vuln["id"], "summary": vuln.get("summary", ""),
            "details": vuln.get("details", ""), "cve_id": next((a for a in aliases if isinstance(a, str) and a.startswith("CVE-")), None),
            "title": vuln.get("summary") or vuln["id"], "description": vuln.get("details") or vuln.get("summary") or vuln["id"],
            "published_at": published, "modified_at": modified, "published": published, "modified": modified,
            "aliases": aliases, "packages": packages, "severity": vuln.get("severity", []), "references": refs},
            metadata={"source": "osv", "published_at": published, "modified_at": modified})


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
                if endpoint.endswith('.zip'):
                    response = await client.get(endpoint, timeout=timeout)
                    return {"status_code": response.status_code, "content": response.content,
                            "error": response.text if response.status_code != 200 else None}
                if endpoint.rstrip('/').endswith(('querybatch', 'querybatch/')):
                    queries = params.pop("queries", [])
                    package_names = params.pop("packages", [])
                    if package_names:
                        queries = [
                            {"package": {"ecosystem": params.get("ecosystem", "PyPI"), "name": name}}
                            for name in package_names
                        ]
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
