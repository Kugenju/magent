"""VulnTell Red Hat Security Data 适配器（阶段 7，Task 7.2）。

将 Red Hat Security Data API (https://access.redhat.com) 响应映射为 SourceRecord。
支持分页、游标、错误分类和 RHSA/CVE 关联。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- Red Hat 生态；版本映射复杂
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
class RedHatConfig:
    """Red Hat Security Data 配置。"""
    endpoint: str = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
    timeout_seconds: float = 30.0
    page_size: int = 100


class RedHatAdapter:
    """Red Hat Security Data 适配器：将 Red Hat API 映射为 SourceRecord 协议。

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
        config: Optional[RedHatConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or RedHatConfig()
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
                    source="redhat",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 Red Hat API 参数
        params = {
            "page": page,
            "limit": min(request.page_size, self._config.page_size),
            "after": request.window_start.date().isoformat(),
            "before": request.window_end.date().isoformat(),
        }

        # 添加过滤条件
        if request.filters.get("cve_id"):
            params["cve"] = request.filters["cve_id"]
        if request.filters.get("rhsa_id"):
            params["rhsa"] = request.filters["rhsa_id"]

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._config.endpoint,
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("redhat", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "redhat",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", [])
            if not isinstance(data, list):
                data = data.get("data", [])

            # Red Hat's public CVE feed is a full list; apply the requested
            # half-open window before mapping so a "past month" request does
            # not accidentally emit historical CVEs.
            windowed = []
            for item in data:
                raw_date = item.get("public_date")
                if raw_date:
                    try:
                        parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        if not (request.window_start <= parsed.astimezone(timezone.utc) < request.window_end):
                            continue
                    except ValueError:
                        pass
                windowed.append(item)

            # 转换为 SourceRecord
            records = []
            for item in windowed:
                cve_id = item.get("CVE", "")
                if not cve_id:
                    continue

                # 提取关键字段
                severity = item.get("severity")
                rhsa_id = item.get("RHSA", "")
                rhsa_url = item.get("RHSA_url", "")
                public_date = item.get("public_date")

                # 提取受影响产品
                affected_products = item.get("affected_products", [])
                packages = []
                for product in affected_products:
                    packages.append({
                        "product": product.get("product", ""),
                        "version": product.get("version", ""),
                    })

                # 提取修复版本
                fix_state = item.get("fix_state")
                package_name = item.get("package_name", "")

                record = SourceRecord(
                    source_record_id=cve_id,
                    payload={
                        "id": cve_id,
                        "rhsa_id": rhsa_id,
                        "rhsa_url": rhsa_url,
                        "severity": severity,
                        "public_date": public_date,
                        "fix_state": fix_state,
                        "package_name": package_name,
                        "packages": packages,
                        # Canonical fields consumed by domain normalization.
                        "cve_id": cve_id,
                        "title": rhsa_id or cve_id,
                        "description": item.get("bugzilla_description") or package_name or "Red Hat security advisory",
                        "published_at": public_date,
                        "modified_at": public_date,
                    },
                    metadata={
                        "source": "redhat",
                        "published_at": public_date,
                        "modified_at": public_date,
                    },
                )
                records.append(record)

            # 计算是否有更多页
            total = len(data)
            has_more = total == self._config.page_size
            next_cursor = str(page + 1) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=page - 1,
                source="redhat",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("redhat", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "Red Hat adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class RedHatTransport:
    """Red Hat Security Data HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 Red Hat API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    endpoint,
                    params={k: v for k, v in params.items() if k not in {"page", "limit"}},
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
