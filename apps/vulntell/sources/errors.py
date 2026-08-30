"""VulnTell 数据源错误分类（阶段 4，Task 4.4）。

定义错误类型、敏感信息脱敏策略和重试提示。

约束：
- 错误对象不保留 Authorization、完整 URL query 或 raw body
- 仅输出 retry hint，由现有执行器策略消费，不在 adapter 内自行循环重试
- 错误分类决策表：
  * 429 -> rate_limited (retryable=True)
  * 408/504 -> timeout (retryable=True)
  * 500/502/503 -> transient (retryable=True)
  * 401 -> auth (retryable=False)
  * 403 -> forbidden (retryable=False)
  * 404 -> not_found (retryable=False)
  * 4xx 其他 -> invalid_response (retryable=False)
  * 网络/解析异常 -> transient (retryable=True)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SourceErrorKind(str, Enum):
    """数据源错误类型。"""
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSIENT = "transient"
    INVALID_RESPONSE = "invalid_response"
    AUTH = "auth"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    PERMANENT = "permanent"
    CANCELLED = "cancelled"


# 重试提示：错误类型 -> (默认可重试, 默认重试延迟秒数)
RETRY_HINTS: dict[SourceErrorKind, tuple[bool, Optional[int]]] = {
    SourceErrorKind.RATE_LIMITED: (True, 60),      # 429: 等待 60s
    SourceErrorKind.TIMEOUT: (True, 5),            # 408/504: 等待 5s
    SourceErrorKind.TRANSIENT: (True, 10),         # 500/502/503/网络异常: 等待 10s
    SourceErrorKind.INVALID_RESPONSE: (False, None),  # 4xx 其他/解析错误
    SourceErrorKind.AUTH: (False, None),           # 401: 需要凭据
    SourceErrorKind.FORBIDDEN: (False, None),      # 403: 权限不足
    SourceErrorKind.NOT_FOUND: (False, None),      # 404: 资源不存在
    SourceErrorKind.PERMANENT: (False, None),      # 不可恢复错误
    SourceErrorKind.CANCELLED: (False, None),      # 用户取消
}


def classify_http_status(status_code: int) -> SourceErrorKind:
    """根据 HTTP 状态码分类错误类型。"""
    if status_code == 429:
        return SourceErrorKind.RATE_LIMITED
    if status_code in (408, 504):
        return SourceErrorKind.TIMEOUT
    if status_code in (401,):
        return SourceErrorKind.AUTH
    if status_code in (403,):
        return SourceErrorKind.FORBIDDEN
    if status_code in (404,):
        return SourceErrorKind.NOT_FOUND
    if status_code in (500, 502, 503):
        return SourceErrorKind.TRANSIENT
    if 400 <= status_code < 500:
        return SourceErrorKind.INVALID_RESPONSE
    if 500 <= status_code < 600:
        return SourceErrorKind.TRANSIENT
    return SourceErrorKind.TRANSIENT


def classify_exception(exc: Exception) -> SourceErrorKind:
    """根据异常类型分类错误类型。"""
    exc_type = type(exc).__name__
    if "Timeout" in exc_type or "asyncio.TimeoutError" in exc_type:
        return SourceErrorKind.TIMEOUT
    if "Connection" in exc_type or "Network" in exc_type:
        return SourceErrorKind.TRANSIENT
    if "JSON" in exc_type or "ValueError" in exc_type or "Parse" in exc_type:
        return SourceErrorKind.INVALID_RESPONSE
    if "Permission" in exc_type or "Forbidden" in exc_type:
        return SourceErrorKind.FORBIDDEN
    if "NotFound" in exc_type or "Missing" in exc_type:
        return SourceErrorKind.NOT_FOUND
    return SourceErrorKind.TRANSIENT


@dataclass(frozen=True)
class SourceError:
    """数据源错误（不可变值对象，脱敏）。

    Attributes:
        source: 来源标识符
        kind: 错误类型
        message: 人类可读错误消息（已脱敏）
        retryable: 是否可重试
        retry_after: 建议重试等待秒数（None 表示不确定）
        http_status: HTTP 状态码（若有，仅用于审计）
        correlation_id: 关联 ID（用于日志关联）
        details: 额外详情（可选，不含敏感信息）
    """
    source: str
    kind: SourceErrorKind
    message: str
    retryable: bool
    retry_after: Optional[int] = None
    http_status: Optional[int] = None
    correlation_id: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_http_status(
        cls,
        source: str,
        status_code: int,
        response_text: str = "",
        correlation_id: Optional[str] = None,
    ) -> "SourceError":
        """从 HTTP 响应创建错误（自动分类和脱敏）。"""
        kind = classify_http_status(status_code)
        retryable, retry_after = RETRY_HINTS[kind]

        # 脱敏：截断响应文本，移除敏感字段
        safe_message = _scrub_message(response_text, status_code)

        return cls(
            source=source,
            kind=kind,
            message=safe_message,
            retryable=retryable,
            retry_after=retry_after,
            http_status=status_code,
            correlation_id=correlation_id,
        )

    @classmethod
    def from_exception(
        cls,
        source: str,
        exc: Exception,
        correlation_id: Optional[str] = None,
    ) -> "SourceError":
        """从异常创建错误（自动分类和脱敏）。"""
        kind = classify_exception(exc)
        retryable, retry_after = RETRY_HINTS[kind]

        # 脱敏：只保留异常类型和简要消息，不包含栈或敏感数据
        safe_message = f"{type(exc).__name__}: {str(exc)[:200]}"

        return cls(
            source=source,
            kind=kind,
            message=safe_message,
            retryable=retryable,
            retry_after=retry_after,
            correlation_id=correlation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 字典。"""
        return {
            "source": self.source,
            "kind": self.kind.value,
            "message": self.message,
            "retryable": self.retryable,
            "retry_after": self.retry_after,
            "http_status": self.http_status,
            "correlation_id": self.correlation_id,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceError":
        """从字典反序列化。"""
        return cls(
            source=data["source"],
            kind=SourceErrorKind(data["kind"]),
            message=data["message"],
            retryable=data["retryable"],
            retry_after=data.get("retry_after"),
            http_status=data.get("http_status"),
            correlation_id=data.get("correlation_id"),
            details=data.get("details", {}),
        )


def _scrub_message(text: str, status_code: int) -> str:
    """脱敏：截断消息，移除潜在敏感字段。"""
    # 截断到 500 字符
    text = text[:500]
    # 移除常见敏感字段（简单启发式）
    for pattern in ["authorization", "api_key", "apikey", "token", "cookie", "secret", "password"]:
        text = text.replace(pattern, "[REDACTED]")
    return f"HTTP {status_code}: {text}" if status_code else text
