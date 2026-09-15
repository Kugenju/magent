"""VulnTell NVD 适配器（阶段 5，Task 5.1，5C.2 扩展）。

将 NVD API (https://services.nvd.nist.gov/rest/json/cves/2.0) 响应映射为 SourceRecord。
支持分页、游标、时间窗口分片、429 限流、超时和错误分类。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 时间窗口超过 120 天自动分片（NVD 限制）
"""

from __future__ import annotations

import json
import gzip
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind, classify_http_status
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


# NVD 时间窗口限制（天）
NVD_MAX_WINDOW_DAYS = 120


@dataclass
class NVDConfig:
    """NVD API 配置。"""
    endpoint: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    page_size: int = 2000  # NVD 最大 page size
    timeout_seconds: float = 30.0
    api_key: Optional[str] = None  # 可选 API key 提高速率限制
    max_window_days: int = NVD_MAX_WINDOW_DAYS  # 最大窗口天数
    max_response_bytes: int = 5 * 1024 * 1024
    max_records_per_page: int = 2000
    # Use official yearly bulk feeds for large historical windows.
    use_bulk: bool = False
    bulk_base_url: str = "https://nvd.nist.gov/feeds/json/cve/2.0"
    bulk_url_template: str = "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{year}.json.gz"


@dataclass
class NVDCursor:
    """NVD 游标：包含窗口分片和分页偏移。"""
    window_start: datetime
    window_end: datetime
    start_index: int
    slice_index: int = 0  # 当前窗口分片索引

    def to_string(self) -> str:
        """序列化为字符串。"""
        data = {
            "ws": self.window_start.isoformat(),
            "we": self.window_end.isoformat(),
            "si": self.start_index,
            "sl": self.slice_index,
        }
        return json.dumps(data, separators=(",", ":"))

    @classmethod
    def from_string(cls, cursor_str: str) -> "NVDCursor":
        """从字符串反序列化。"""
        try:
            data = json.loads(cursor_str)
            return cls(
                window_start=datetime.fromisoformat(data["ws"]),
                window_end=datetime.fromisoformat(data["we"]),
                start_index=data["si"],
                slice_index=data.get("sl", 0),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            raise ValueError(f"Invalid NVD cursor: {cursor_str}")


def slice_time_window(
    window_start: datetime,
    window_end: datetime,
    max_days: int = NVD_MAX_WINDOW_DAYS,
) -> list[tuple[datetime, datetime]]:
    """将时间窗口切分为 NVD 允许的最大区间。

    NVD API 限制查询窗口不超过 120 天。
    返回 [(start, end), ...] 列表，每个区间不超过 max_days 天。
    """
    if max_days <= 0:
        raise ValueError("max_days must be positive")
    slices = []
    current_start = window_start

    while current_start < window_end:
        current_end = min(current_start + timedelta(days=max_days), window_end)
        slices.append((current_start, current_end))
        current_start = current_end

    return slices


class NVDAdapter:
    """NVD 适配器：将 NVD CVE API 映射为 SourceRecord 协议。

    支持：
    - 分页：使用 startIndex 和 resultsPerPage
    - 游标：格式 "{startIndex}"，整数偏移
    - 窗口：lastModStartDate/lastModEndDate（半开区间 [start, end)）
    - 时间窗口分片：自动将大窗口切分为 120 天区间
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

    def _get_window_slices(
        self, request: SourceRequest, cursor: Optional[NVDCursor] = None
    ) -> list[tuple[datetime, datetime]]:
        """获取当前请求的窗口分片列表。"""
        if cursor:
            # 从游标恢复：返回剩余分片
            slices = slice_time_window(
                cursor.window_start,
                cursor.window_end,
                self._config.max_window_days,
            )
            return slices[cursor.slice_index:]
        else:
            # 新请求：切分整个窗口
            return slice_time_window(
                request.window_start,
                request.window_end,
                self._config.max_window_days,
            )

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage | SourceError:
        """获取一页数据。

        Args:
            request: 同步请求
            cursor: 分页游标（JSON 格式，包含窗口分片和偏移）

        Returns:
            SourcePage 或 SourceError
        """
        if self._config.use_bulk:
            return await self._fetch_bulk_page(request, cursor)

        # 解析游标
        nvd_cursor = None
        if cursor:
            try:
                nvd_cursor = NVDCursor.from_string(cursor)
            except ValueError:
                return SourceError(
                    source="nvd",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )
            if nvd_cursor.start_index < 0 or nvd_cursor.slice_index < 0:
                return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                    message="Invalid cursor values", retryable=False)

        # 获取窗口分片
        slices = self._get_window_slices(request, nvd_cursor)
        if not slices:
            return SourceError(
                source="nvd",
                kind=SourceErrorKind.INVALID_RESPONSE,
                message="No window slices available",
                retryable=False,
            )

        # 使用第一个分片
        slice_start, slice_end = slices[0]
        start_index = nvd_cursor.start_index if nvd_cursor else 0

        # 构建 NVD API 参数
        params = {
            "startIndex": start_index,
            "resultsPerPage": min(request.page_size, self._config.page_size),
            "lastModStartDate": slice_start.isoformat(),
            "lastModEndDate": slice_end.isoformat(),
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
            return SourceError.from_http_status("nvd", status_code, response.get("error", ""))

        try:
            data = response.get("data", {})
            try:
                if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > self._config.max_response_bytes:
                    return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                       message="Response exceeds size limit", retryable=False)
            except (TypeError, ValueError):
                return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                   message="Invalid response payload", retryable=False)
            vulnerabilities = data.get("vulnerabilities", [])
            total_results = data.get("totalResults", 0)
            if not isinstance(vulnerabilities, list) or len(vulnerabilities) > self._config.max_records_per_page:
                return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                   message="Response record count exceeds limit", retryable=False)
            vulnerabilities = sorted(vulnerabilities,
                key=lambda v: ((v.get("cve", {}).get("lastModified") or ""),
                               (v.get("cve", {}).get("id") or "")))
            records = [self._cve_to_record(v.get("cve", {}),
                       f"{slice_start.isoformat()}/{slice_end.isoformat()}")
                       for v in vulnerabilities if v.get("cve", {}).get("id")]
            server_count = data.get("resultsPerPage", len(vulnerabilities))
            try: server_count = int(server_count)
            except (TypeError, ValueError): server_count = len(vulnerabilities)
            next_index = start_index + max(0, server_count)
            has_more_in_slice = next_index < total_results
            has_more_slices = len(slices) > 1
            if has_more_in_slice:
                next_cursor = NVDCursor(request.window_start, request.window_end, next_index,
                                        nvd_cursor.slice_index if nvd_cursor else 0).to_string()
            elif has_more_slices:
                next_cursor = NVDCursor(request.window_start, request.window_end, 0,
                                        (nvd_cursor.slice_index if nvd_cursor else 0) + 1).to_string()
            else:
                next_cursor = None
            return SourcePage(records=tuple(records), next_cursor=next_cursor,
                              has_more=next_cursor is not None,
                              page_index=start_index // max(1, request.page_size),
                              source="nvd", observed_at=datetime.now(timezone.utc),
                              request_fingerprint=request.request_fingerprint)
        except Exception as exc:
            return SourceError.from_exception("nvd", exc)

    async def _fetch_bulk_page(self, request: SourceRequest, cursor: Optional[str]) -> SourcePage | SourceError:
        """Fetch official yearly ``nvdcve-2.0-YYYY.json.gz`` feeds.

        Cursor is a compact JSON object containing year index and record offset;
        feed contents are cached per year for checkpoint-safe pagination.
        """
        try:
            start_year = request.window_start.astimezone(timezone.utc).year
            end_year = (request.window_end - timedelta(microseconds=1)).astimezone(timezone.utc).year
            years = list(range(start_year, end_year + 1))
            yi, offset = 0, 0
            if cursor:
                try:
                    c = json.loads(cursor); yi, offset = int(c["y"]), int(c.get("o", 0))
                except Exception:
                    return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE, message="Invalid cursor format", retryable=False)
            if yi < 0 or yi >= len(years) or offset < 0:
                return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE, message="Invalid cursor values", retryable=False)
            if not hasattr(self, "_bulk_cache"):
                self._bulk_cache = {}
            year = years[yi]
            records = self._bulk_cache.get(year)
            if records is None:
                template = self._config.bulk_url_template
                if template == NVDConfig.__dataclass_fields__["bulk_url_template"].default and self._config.bulk_base_url != NVDConfig.__dataclass_fields__["bulk_base_url"].default:
                    template = self._config.bulk_base_url.rstrip("/") + "/nvdcve-2.0-{year}.json.gz"
                endpoint = template.format(year=year)
                response = await self._transport(endpoint=endpoint, params={}, api_key=self._config.api_key, timeout=self._config.timeout_seconds)
                if response.get("status_code", 500) != 200:
                    return SourceError.from_http_status("nvd", response.get("status_code", 500), response.get("error", ""))
                blob = response.get("content")
                if blob is None:
                    data = response.get("data")
                    if isinstance(data, (bytes, bytearray)): blob = data
                if not blob:
                    return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE, message="Bulk feed missing content", retryable=False)
                raw = gzip.decompress(blob) if bytes(blob)[:2] == b"\x1f\x8b" else bytes(blob)
                data = json.loads(raw.decode("utf-8"))
                vulns = data.get("vulnerabilities", []) if isinstance(data, dict) else []
                parsed = []
                for vuln in vulns:
                    cve = vuln.get("cve", {}) if isinstance(vuln, dict) else {}
                    pub, mod = cve.get("published"), cve.get("lastModified")
                    in_window = False
                    for stamp in (pub, mod):
                        if not stamp: continue
                        try:
                            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                            if request.window_start <= dt.astimezone(timezone.utc) < request.window_end:
                                in_window = True; break
                        except ValueError:
                            pass
                    if in_window and cve.get("id"):
                        parsed.append(self._cve_to_record(cve, f"bulk-{year}"))
                records = tuple(parsed)
                self._bulk_cache[year] = records
            size = min(request.page_size, self._config.page_size)
            page = records[offset:offset + size]
            new_offset = offset + len(page)
            if new_offset < len(records):
                next_cursor = json.dumps({"y": yi, "o": new_offset}, separators=(",", ":"))
            elif yi + 1 < len(years):
                next_cursor = json.dumps({"y": yi + 1, "o": 0}, separators=(",", ":"))
            else:
                next_cursor = None
            return SourcePage(records=tuple(page), next_cursor=next_cursor, has_more=next_cursor is not None,
                              page_index=offset // max(1, size), source="nvd", observed_at=datetime.now(timezone.utc),
                              request_fingerprint=request.request_fingerprint)
        except Exception as exc:
            return SourceError.from_exception("nvd", exc)

    def _cve_to_record(self, cve: dict[str, Any], window_slice: str = "") -> SourceRecord:
        record_id = cve.get("id", "")
        descriptions = [d for d in cve.get("descriptions", []) if d.get("lang") == "en"][:1]
        metrics = cve.get("metrics", {}) or {}
        metric = (metrics.get("cvssMetricV31") or metrics.get("cvssMetricV30") or metrics.get("cvssMetricV2") or [{}])[0]
        cvss_data = metric.get("cvssData", {}) if isinstance(metric, dict) else {}
        return SourceRecord(source_record_id=record_id, payload={"id": record_id, "published": cve.get("published"), "lastModified": cve.get("lastModified"), "descriptions": descriptions, "cve_id": record_id, "title": descriptions[0].get("value") if descriptions else record_id, "description": descriptions[0].get("value") if descriptions else None, "published_at": cve.get("published"), "modified_at": cve.get("lastModified"), "cvss_score": cvss_data.get("baseScore"), "cvss_vector": cvss_data.get("vectorString"), "cvss_version": cvss_data.get("version")}, metadata={"source": "nvd", "published_at": cve.get("published"), "modified_at": cve.get("lastModified"), "window_slice": window_slice})

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
            # 限制响应大小，避免误将巨大 payload 写入内存/状态
            try:
                if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > self._config.max_response_bytes:
                    return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                        message="Response exceeds size limit", retryable=False)
            except (TypeError, ValueError):
                return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                   message="Invalid response payload", retryable=False)
            vulnerabilities = data.get("vulnerabilities", [])
            total_results = data.get("totalResults", 0)

            if not isinstance(vulnerabilities, list) or len(vulnerabilities) > self._config.max_records_per_page:
                return SourceError(source="nvd", kind=SourceErrorKind.INVALID_RESPONSE,
                                   message="Response record count exceeds limit", retryable=False)

            # NVD 返回通常已排序，但显式以 modified time + id 稳定排序，确保分片间可重现
            vulnerabilities = sorted(
                vulnerabilities,
                key=lambda v: ((v.get("cve", {}).get("lastModified") or ""),
                               (v.get("cve", {}).get("id") or "")),
            )

            # 转换为 SourceRecord
            records = []
            for vuln in vulnerabilities:
                cve = vuln.get("cve", {})
                record_id = cve.get("id", "")
                if not record_id:
                    continue

                # 提取关键字段（不保存完整 payload）
                descriptions = [
                    d for d in cve.get("descriptions", [])
                    if d.get("lang") == "en"
                ][:1]
                metrics = cve.get("metrics", {}) or {}
                metric = (metrics.get("cvssMetricV31") or metrics.get("cvssMetricV30") or metrics.get("cvssMetricV2") or [{}])[0]
                cvss_data = metric.get("cvssData", {}) if isinstance(metric, dict) else {}
                record = SourceRecord(
                    source_record_id=record_id,
                    payload={
                        "id": record_id,
                        "published": cve.get("published"),
                        "lastModified": cve.get("lastModified"),
                        "descriptions": descriptions,  # 只保留英文描述
                        # Canonical fields consumed by domain normalization.
                        "cve_id": record_id,
                        "title": (descriptions[0].get("value") if descriptions else record_id),
                        "description": (descriptions[0].get("value") if descriptions else None),
                        "published_at": cve.get("published"),
                        "modified_at": cve.get("lastModified"),
                        "cvss_score": cvss_data.get("baseScore"),
                        "cvss_vector": cvss_data.get("vectorString"),
                        "cvss_version": cvss_data.get("version"),
                    },
                    metadata={
                        "source": "nvd",
                        "published_at": cve.get("published"),
                        "modified_at": cve.get("lastModified"),
                        "window_slice": f"{slice_start.isoformat()}/{slice_end.isoformat()}",
                    },
                )
                records.append(record)

            # 计算是否有更多页
            # 游标必须使用服务端偏移，而非过滤后的有效记录数；否则坏记录会导致重复/跳过 CVE
            server_count = data.get("resultsPerPage", len(vulnerabilities))
            try:
                server_count = int(server_count)
            except (TypeError, ValueError):
                server_count = len(vulnerabilities)
            server_count = max(0, server_count)
            next_index = start_index + server_count
            has_more_in_slice = next_index < total_results
            has_more_slices = len(slices) > 1

            # 构建下一页游标
            if has_more_in_slice:
                # 当前分片还有更多页
                next_cursor = NVDCursor(
                    window_start=nvd_cursor.window_start if nvd_cursor else request.window_start,
                    window_end=nvd_cursor.window_end if nvd_cursor else request.window_end,
                    start_index=next_index,
                    slice_index=nvd_cursor.slice_index if nvd_cursor else 0,
                ).to_string()
            elif has_more_slices:
                # 还有更多分片
                next_cursor = NVDCursor(
                    window_start=nvd_cursor.window_start if nvd_cursor else request.window_start,
                    window_end=nvd_cursor.window_end if nvd_cursor else request.window_end,
                    start_index=0,
                    slice_index=(nvd_cursor.slice_index if nvd_cursor else 0) + 1,
                ).to_string()
            else:
                next_cursor = None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
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
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

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
                if endpoint.endswith(".json.gz"):
                    return {
                        "status_code": response.status_code,
                        "content": response.content if response.status_code == 200 else None,
                        "error": response.text if response.status_code != 200 else None,
                    }
                return {
                    "status_code": response.status_code,
                    "data": response.json() if response.status_code == 200 else None,
                    "error": response.text if response.status_code != 200 else None,
                }
            except httpx.TimeoutException:
                return {"status_code": 408, "error": "Request timed out"}
            except httpx.RequestError as exc:
                return {"status_code": 500, "error": str(exc)}
