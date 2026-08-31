"""VulnTell CNVD 适配器（阶段 5，Task 5.3，5C.4 合规文档）。

将 CNVD（国家信息安全漏洞共享平台）API 映射为 SourceRecord。
支持中文字段、CVE 关联、分页和错误分类。

约束：
- 默认不联网，需要显式传入 transport
- fixture/录制响应仅保存最小脱敏样本
- 不把完整 raw payload 写入 State/Trace/日志
- 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试
- 保留中文与跨源冲突，不在 adapter 内做领域去重或指标计算

## 合规说明（5C.4）

根据审查结果，CNVD 官方 endpoint (https://www.cnvd.org.cn/flaw/list) 返回 HTTP 521 和
JavaScript 反爬挑战，无法通过程序化方式获取结构化漏洞记录。

### 合规路径

1. **官方 API**：CNVD 未提供公开 REST API，仅支持 Web 界面查询
2. **人工下载**：允许用户从 CNVD 网站手动下载漏洞数据，格式为 CSV/Excel
3. **Fixture 模式**：使用脱敏的 fixture 数据进行测试和开发

### 使用方式

```bash
# 默认使用 fixture 模式
python -m apps.vulntell --no-llm --json

# 如有官方授权 API，可启用 live 模式（当前不支持）
# python -m apps.vulntell --live --source cnvd
```

### 法律合规

- 不绕过 JavaScript/WAF 或抓取引用页面
- 不把反爬页面写入漏洞记录
- 许可和保留策略见 THIRD_PARTY_NOTICES.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from apps.vulntell.sources.errors import SourceError, SourceErrorKind, classify_http_status
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


@dataclass
class CNVDConfig:
    """CNVD 配置。"""
    endpoint: str = "https://www.cnvd.org.cn/flaw/list"
    page_size: int = 20  # CNVD 默认 page size
    timeout_seconds: float = 30.0
    api_key: Optional[str] = None  # 可选 API key


class CNVDAdapter:
    """CNVD 适配器：将 CNVD API 映射为 SourceRecord 协议。

    支持：
    - 分页：使用 page 和 rows 参数
    - 游标：格式 "{page}"，整数页码
    - 错误分类：429/408/5xx/401/403/404

    约束：
    - 默认不联网，需要传入 transport 函数
    - 由 runner 统一执行重试，adapter 不自行循环重试
    - 保留中文字段编码，不修改原始中文内容
    - 官方 API 暂不可用，仅支持 fixture 模式
    """

    def __init__(
        self,
        config: Optional[CNVDConfig] = None,
        transport: Optional[Callable] = None,
    ) -> None:
        self._config = config or CNVDConfig()
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
        page_number = 1
        if cursor:
            try:
                page_number = int(cursor)
            except ValueError:
                return SourceError(
                    source="cnvd",
                    kind=SourceErrorKind.INVALID_RESPONSE,
                    message="Invalid cursor format",
                    retryable=False,
                )

        # 构建 CNVD API 参数
        params = {
            "page": page_number,
            "rows": min(request.page_size, self._config.page_size),
        }

        # 添加过滤条件
        if request.filters.get("cnvd_id"):
            params["cnvdId"] = request.filters["cnvd_id"]
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
            return SourceError.from_exception("cnvd", exc)

        # 检查 HTTP 状态码
        if response.get("status_code", 200) != 200:
            status_code = response.get("status_code", 500)
            return SourceError.from_http_status(
                "cnvd",
                status_code,
                response.get("error", ""),
            )

        # 解析响应
        try:
            data = response.get("data", {})
            records_data = data.get("records", [])
            total = data.get("total", 0)

            # 转换为 SourceRecord
            records = []
            for item in records_data:
                cnvd_id = item.get("cnvdId", "")
                if not cnvd_id:
                    continue

                # 提取关键字段（不保存完整 payload）
                record = SourceRecord(
                    source_record_id=cnvd_id,
                    payload={
                        "cnvdId": cnvd_id,
                        "cveId": item.get("cveId"),
                        "title": item.get("title"),
                        "level": item.get("level"),
                        "type": item.get("type"),
                        "publishedDate": item.get("publishedDate"),
                        "dueDate": item.get("dueDate"),
                        "source": item.get("source"),
                    },
                    metadata={
                        "source": "cnvd",
                        "published_at": item.get("publishedDate"),
                        "modified_at": item.get("publishedDate"),
                    },
                )
                records.append(record)

            # 计算是否有更多页
            total_pages = (total + self._config.page_size - 1) // self._config.page_size
            has_more = page_number < total_pages
            next_cursor = str(page_number + 1) if has_more else None

            return SourcePage(
                records=tuple(records),
                next_cursor=next_cursor,
                has_more=has_more,
                page_index=page_number - 1,
                source="cnvd",
                observed_at=datetime.now(timezone.utc),
                request_fingerprint=request.request_fingerprint,
            )

        except Exception as exc:
            return SourceError.from_exception("cnvd", exc)

    async def _default_transport(
        self,
        endpoint: str,
        params: dict,
        api_key: Optional[str],
        timeout: float,
    ) -> dict:
        """默认 transport：抛出 NotImplementedError。"""
        raise NotImplementedError(
            "CNVD adapter requires a transport function. "
            "Use httpx or aiohttp transport for live mode."
        )


class CNVDTransport:
    """CNVD HTTP transport（使用 httpx）。"""

    async def __call__(
        self,
        endpoint: str,
        params: dict,
        api_key: Optional[str],
        timeout: float,
    ) -> dict:
        """调用 CNVD API。"""
        # httpx 在函数内导入，避免顶层导入网络库
        try:
            import httpx
        except ImportError:
            return {"status_code": 500, "error": "httpx not installed"}

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

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
