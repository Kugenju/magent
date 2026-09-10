"""VulnTell Ubuntu CVE Tracker 适配器（阶段 7，Task 7.3）。

将 Ubuntu CVE Tracker 数据映射为 SourceRecord。
支持 Git 仓库数据、分页和错误分类。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- Git 同步；需保留 Ubuntu release 维度
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
class UbuntuConfig:
    """Ubuntu CVE Tracker 配置。"""
    endpoint: str = "https://ubuntu.com/security/cves.json"
    timeout_seconds: float = 30.0
    page_size: int = 100


class UbuntuAdapter:
    """Ubuntu CVE Tracker 适配器：将 Ubuntu API 映射为 SourceRecord 协议。

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
        config: Optional[UbuntuConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or UbuntuConfig()
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
                    source="ubuntu",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 Ubuntu API 参数
        params = {
            "page": page,
            "limit": min(request.page_size, self._config.page_size),
            "after": request.window_start.date().isoformat(),
            "before": request.window_end.date().isoformat(),
        }

        # 添加过滤条件
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
            return SourceError.from_exception("ubuntu", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "ubuntu",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {})
            # Ubuntu's public endpoint returns ``cves``; retain support for
            # the older notice-shaped fixture used by compatibility tests.
            notices = data.get("notices", [])
            if not notices and isinstance(data.get("cves"), list):
                notices = [
                    {
                        "id": item.get("id"),
                        "title": item.get("id"),
                        "description": item.get("description"),
                        "published": item.get("published"),
                        "updated": item.get("updated_at"),
                        "severity": item.get("priority"),
                        "priority": item.get("priority"),
                        "packages": item.get("packages", []),
                        "references": item.get("references", []),
                    }
                    for item in data["cves"]
                    if isinstance(item, dict)
                ]

            # Ubuntu's feed is also a rolling/full collection.  Restrict
            # records by updated (or published) timestamp at the adapter
            # boundary, preserving only the requested half-open window.
            windowed = []
            for notice in notices:
                raw_date = notice.get("updated") or notice.get("published")
                if raw_date:
                    try:
                        parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        if not (request.window_start <= parsed.astimezone(timezone.utc) < request.window_end):
                            continue
                    except ValueError:
                        pass
                windowed.append(notice)

            # 转换为 SourceRecord
            records = []
            for notice in windowed:
                notice_id = notice.get("id", "")
                if not notice_id:
                    continue

                # 提取关键字段
                title = notice.get("title", "")
                description = notice.get("description", "")
                published = notice.get("published")
                updated = notice.get("updated")
                severity = notice.get("severity")
                priority = notice.get("priority")

                # 提取受影响包
                packages = notice.get("packages", [])
                affected_packages = []
                for pkg in packages:
                    if isinstance(pkg, dict):
                        affected_packages.append({
                            "name": pkg.get("name", ""),
                            "version": pkg.get("version", ""),
                            "release": pkg.get("release", ""),
                        })
                    elif isinstance(pkg, str) and pkg:
                        affected_packages.append({"name": pkg, "version": "", "release": ""})

                # 提取引用
                references = []
                for ref in notice.get("references", []):
                    if isinstance(ref, dict):
                        references.append({"type": ref.get("type", "WEB"), "url": ref.get("url", "")})
                    elif isinstance(ref, str) and ref.startswith("http"):
                        references.append({"type": "WEB", "url": ref})

                record = SourceRecord(
                    source_record_id=notice_id,
                    payload={
                        "id": notice_id,
                        "title": title,
                        "description": description,
                        "published": published,
                        "updated": updated,
                        "severity": severity,
                        "priority": priority,
                        "packages": affected_packages,
                        "references": references,
                        # Canonical fields consumed by domain normalization.
                        "cve_id": notice_id if str(notice_id).startswith("CVE-") else None,
                        "title": title or notice_id,
                        "description": description or title or notice_id,
                        "published_at": published,
                        "modified_at": updated,
                    },
                    metadata={
                        "source": "ubuntu",
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
                source="ubuntu",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("ubuntu", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "Ubuntu adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class UbuntuTransport:
    """Ubuntu CVE Tracker HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 Ubuntu API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient() as client:
            try:
                query = {} if endpoint.rstrip("/").endswith("cves.json") else params
                response = await client.get(
                    endpoint,
                    params=query,
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
