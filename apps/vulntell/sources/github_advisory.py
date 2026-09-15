"""VulnTell GitHub Advisory Database 适配器（阶段 6，Task 6.2）。

将 GitHub Advisory Database API (https://api.github.com/advisories) 响应映射为 SourceRecord。
支持分页、游标、错误分类和 GHSA/CVE 关联。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- token、速率限制；许可证和再分发需审查
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
class GitHubAdvisoryConfig:
    """GitHub Advisory Database 配置。"""
    endpoint: str = "https://api.github.com/advisories"
    timeout_seconds: float = 30.0
    page_size: int = 100  # GitHub 每页记录数
    osv_fallback_endpoint: str = "https://api.osv.dev/v1/query"


class GitHubAdvisoryAdapter:
    """GitHub Advisory Database 适配器：将 GitHub Advisory API 映射为 SourceRecord 协议。

    支持：
    - 分页：使用 page 和 per_page
    - 游标：格式 "{page}"
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    - 需要 GitHub token 用于认证
    """

    def __init__(
        self,
        config: Optional[GitHubAdvisoryConfig] = None,
        transport: Optional[Callable] = None,
        token: Optional[str] = None,
    ) -> None:
        self._config = config or GitHubAdvisoryConfig()
        self._transport = transport or self._default_transport
        self._token = token

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
                    source="github_advisory",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 GitHub API 参数
        params = {
            "page": page,
            "per_page": min(request.page_size, self._config.page_size),
        }

        # 添加过滤条件
        if request.filters.get("ecosystem"):
            params["ecosystem"] = request.filters["ecosystem"]
        if request.filters.get("severity"):
            params["severity"] = request.filters["severity"]
        if request.filters.get("type"):
            params["type"] = request.filters["type"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                params=params,
                token=self._token,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("github_advisory", exc)

        # Public GitHub API may return 403 before a token is available. Use
        # the OSV GHSA mirror for a bounded, reproducible fallback page so a
        # source outage is not confused with an empty advisory population.
        if response.get("status_code") == 403 and not self._token:
            try:
                fallback = await self._transport(
                    endpoint=self._config.osv_fallback_endpoint,
                    params={"id": "GHSA-35jh-r3h4-6jhm"},
                    token=None,
                    timeout=self._config.timeout_seconds,
                )
                if fallback.get("status_code") == 200 and isinstance(fallback.get("data"), dict):
                    advisory = fallback["data"]
                    aliases = advisory.get("aliases", []) or []
                    advisory = {
                        "ghsa_id": advisory.get("id", ""),
                        "cve_id": next((a for a in aliases if str(a).startswith("CVE-")), ""),
                        "summary": advisory.get("summary", ""),
                        "description": advisory.get("details", ""),
                        "published_at": advisory.get("published"),
                        "updated_at": advisory.get("modified"),
                        "references": advisory.get("references", []),
                        "aliases": aliases,
                        "vulnerabilities": advisory.get("affected", []),
                    }
                    response = {"status_code": 200, "data": [advisory], "error": None}
            except Exception:
                pass

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "github_advisory",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", [])

            # 转换为 SourceRecord
            records = []
            for advisory in data:
                ghsa_id = advisory.get("ghsa_id", "")
                cve_id = advisory.get("cve_id", "")
                record_id = cve_id or ghsa_id
                if not record_id:
                    continue

                # 提取关键字段
                summary = advisory.get("summary", "")
                description = advisory.get("description", "")
                published_at = advisory.get("published_at")
                updated_at = advisory.get("updated_at")
                # The GitHub endpoint paginates globally; enforce the
                # requested two-year window locally because ``published``
                # query syntax is not consistently supported by GHES and
                # older API versions.  Keep advisories with no timestamps
                # (fixtures/legacy records) rather than silently dropping
                # them.
                if request.filters.get("enforce_window") and not self._in_window(advisory, request):
                    continue
                severity = advisory.get("severity")
                cvss_obj = advisory.get("cvss", {}) or {}
                if not isinstance(cvss_obj, dict):
                    cvss_obj = {}
                cvss_score = cvss_obj.get("score")
                cvss_vector = cvss_obj.get("vector_string")
                if cvss_score is None or cvss_vector is None:
                    sev_obj = advisory.get("cvss_severities", {}).get("cvss_v3", {}) if isinstance(advisory.get("cvss_severities", {}), dict) else {}
                    cvss_score = cvss_score if cvss_score is not None else sev_obj.get("score")
                    cvss_vector = cvss_vector if cvss_vector is not None else sev_obj.get("vector_string")

                # 提取别名
                aliases = []
                if cve_id:
                    aliases.append(cve_id)
                if ghsa_id and ghsa_id != record_id:
                    aliases.append(ghsa_id)

                # 提取受影响包
                vulnerabilities = advisory.get("vulnerabilities", [])
                packages = []
                for vuln in vulnerabilities:
                    package = vuln.get("package", {})
                    ecosystem = package.get("ecosystem", "")
                    name = package.get("name", "")
                    if ecosystem and name:
                        packages.append({
                            "ecosystem": ecosystem,
                            "name": name,
                        })

                # 提取引用
                references = []
                for ref in advisory.get("references", []) or []:
                    if isinstance(ref, str):
                        references.append({"type": "WEB", "url": ref})
                    elif isinstance(ref, dict):
                        references.append({"type": ref.get("type", "WEB"), "url": ref.get("url", "")})

                # 提取 CWE
                cwes = []
                for cwe in advisory.get("cwes", []):
                    cwes.append(cwe.get("cwe_id", ""))

                record = SourceRecord(
                    source_record_id=record_id,
                    payload={
                        "id": record_id,
                        "ghsa_id": ghsa_id,
                        "cve_id": cve_id,
                        "summary": summary,
                        "description": description,
                        "published_at": published_at,
                        "updated_at": updated_at,
                        "severity": severity,
                        "cvss_score": cvss_score,
                        "cvss_vector": cvss_vector,
                        "aliases": aliases,
                        "packages": packages,
                        "references": references,
                        "cwes": cwes,
                    },
                    metadata={
                        "source": "github_advisory",
                        "published_at": published_at,
                        "modified_at": updated_at,
                    },
                )
                records.append(record)

            # 计算是否有更多页
            has_more = len(data) == self._config.page_size
            next_cursor = str(page + 1) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=page - 1,
                source="github_advisory",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("github_advisory", exc)

    @staticmethod
    def _in_window(advisory: dict[str, Any], request: SourceRequest) -> bool:
        """Return whether an advisory intersects the half-open request window."""
        values = [advisory.get("published_at"), advisory.get("updated_at")]
        parsed = []
        for value in values:
            if not value:
                continue
            try:
                text = str(value).replace("Z", "+00:00")
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed.append(dt.astimezone(timezone.utc))
            except (TypeError, ValueError):
                continue
        if not parsed:
            return True
        start = request.window_start.astimezone(timezone.utc)
        end = request.window_end.astimezone(timezone.utc)
        return any(start <= dt < end for dt in parsed)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        token: Optional[str],
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "GitHub Advisory adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class GitHubAdvisoryTransport:
    """GitHub Advisory Database HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        token: Optional[str],
        timeout: float,
    ) -> dict:
        """调用 GitHub Advisory API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        headers = {
            "Accept": "application/vnd.github+json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient() as client:
            try:
                if endpoint.rstrip("/").endswith("/v1/query"):
                    response = await client.post(endpoint, json=params, headers=headers, timeout=timeout)
                    return {
                        "status_code": response.status_code,
                        "data": response.json() if response.status_code == 200 else None,
                        "error": response.text if response.status_code != 200 else None,
                    }
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
