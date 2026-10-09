"""VulnTell EUVD 适配器（阶段 6，Task 6.3；2026-09 按最新 ENISA EUVD API 重写）。

将 ENISA EUVD API (https://euvdservices.enisa.europa.eu/api) 响应映射为
SourceRecord。旧实现基于已失效的占位 endpoint（europeanswift.org），现迁移到
官方公开接口：

- 列表/检索：``GET {endpoint}/search``，参数 ``fromDate``/``toDate``
  （YYYY-MM-DD）、``page``（0 起）、``size``、``text``，返回
  ``{"items": [...], "total": N}``
- 最新漏洞：``GET {endpoint}/lastvulnerabilities``

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 接口与字段可能演进；需记录版本
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest

# EUVD datePublished/dateUpdated 格式，如 "Sep 10, 2024, 4:53:56 PM"（UTC）
_EUVD_DT_FORMAT = "%b %d, %Y, %I:%M:%S %p"


@dataclass
class EUVDConfig:
    """EUVD 配置。"""
    endpoint: str = "https://euvdservices.enisa.europa.eu/api"
    timeout_seconds: float = 30.0
    page_size: int = 100  # EUVD 每页记录数


def _parse_euvd_datetime(value: object) -> Optional[str]:
    """解析 EUVD 时间字符串为 ISO-8601 UTC；失败返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, _EUVD_DT_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        # 兼容 ISO 格式
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return parsed.astimezone(timezone.utc).isoformat()


def _split_lines(value: object) -> list[str]:
    """EUVD 的 aliases/references 是换行分隔字符串。"""
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


class EUVDAdapter:
    """EUVD 适配器：将 ENISA EUVD API 映射为 SourceRecord 协议。

    支持：
    - 分页：API 为 0 起 ``page``；对外游标为 1 起页码，格式 "{page}"
    - 窗口：服务端 ``fromDate``/``toDate`` 粗过滤 + 客户端按
      ``datePublished`` 半开区间 [window_start, window_end) 精确过滤
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    """

    def __init__(
        self,
        config: Optional[EUVDConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or EUVDConfig()
        self._transport = transport or self._default_transport

    def _search_url(self) -> str:
        endpoint = self._config.endpoint.rstrip("/")
        if endpoint.endswith("/search"):
            return endpoint
        return endpoint + "/search"

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（格式 "{page}"，1 起）

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
                    source="euvd",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        size = min(request.page_size, self._config.page_size)
        params = {
            # API page 从 0 开始
            "page": page - 1,
            "size": size,
            "fromDate": request.window_start.date().isoformat(),
            "toDate": request.window_end.date().isoformat(),
        }

        # 添加过滤条件：EUVD search 使用全文 text 参数
        text_query = (
            request.filters.get("text")
            or request.filters.get("cve_id")
            or request.filters.get("vendor")
            or request.filters.get("product")
        )
        if text_query:
            params["text"] = text_query

        # 调用 API
        try:
            response = await self._transport(
                endpoint=self._search_url(),
                params=params,
                timeout=self._config.timeout_seconds,
            )
        except Exception as exc:
            return SourceError.from_exception("euvd", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "euvd",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data") or {}
            items = data.get("items") or []
            total = int(data.get("total") or 0)

            records = []
            for item in items:
                euvd_id = item.get("id", "")
                if not euvd_id:
                    continue

                # 时间字段：转换为 ISO-8601 UTC；客户端窗口过滤需要解析值
                published = _parse_euvd_datetime(item.get("datePublished"))
                modified = _parse_euvd_datetime(item.get("dateUpdated"))

                # 客户端半开窗口过滤（服务端 fromDate/toDate 为日期粒度）
                if published:
                    pub_dt = datetime.fromisoformat(published)
                    if not (request.window_start <= pub_dt < request.window_end):
                        continue

                # 别名：换行分隔字符串；提取 CVE 作为 canonical cve_id
                aliases = _split_lines(item.get("aliases"))
                cve_id = next((a for a in aliases if a.startswith("CVE-")), None)

                # 受影响产品
                packages = []
                for entry in item.get("enisaIdProduct") or []:
                    if not isinstance(entry, dict):
                        continue
                    product = entry.get("product") or {}
                    vendor = (product.get("vendor") or {}).get("name", "")
                    packages.append({
                        "vendor": vendor,
                        "product": product.get("name", ""),
                        "versions": [entry["product_version"]] if entry.get("product_version") else [],
                    })

                # 引用：换行分隔 URL 字符串
                references = [
                    {"type": "WEB", "url": url}
                    for url in _split_lines(item.get("references"))
                ]

                base_score = item.get("baseScore")
                description = item.get("description", "")

                record = SourceRecord(
                    source_record_id=euvd_id,
                    payload={
                        "id": euvd_id,
                        "cve_id": cve_id,
                        "title": description.split("\n", 1)[0][:200] if description else euvd_id,
                        "description": description,
                        "published_at": published,
                        "modified_at": modified,
                        "cvss_score": base_score,
                        "cvss_vector": item.get("baseScoreVector"),
                        "cvss_version": item.get("baseScoreVersion"),
                        "aliases": aliases,
                        "affected": packages,
                        "packages": packages,
                        "references": references,
                        "assigner": item.get("assigner"),
                        "epss": item.get("epss"),
                        "enisa_uuid": item.get("enisaUuid"),
                    },
                    metadata={
                        "source": "euvd",
                        "published_at": published,
                        "modified_at": modified,
                    },
                )
                records.append(record)

            # 计算是否有更多页：page 为 1 起
            has_more = page * size < total
            next_cursor = str(page + 1) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=page - 1,
                source="euvd",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("euvd", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "EUVD adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class EUVDTransport:
    """EUVD HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        timeout: float,
    ) -> dict:
        """调用 EUVD API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        async with httpx.AsyncClient(follow_redirects=True) as client:
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
