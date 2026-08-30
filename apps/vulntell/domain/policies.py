"""领域策略常量（阶段 2 迁移）。

集中定义跨源优先级、相关性画像、最小样本阈值与字段校验正则，供 normalize /
dedupe / metrics 共享，避免策略散落导致双份实现漂移。本模块为纯常量/正则，无网络
或框架副作用，可被 apps.vulntell.domain 独立导入。
"""

from __future__ import annotations

import re

# 跨源合并优先级（数值越小优先级越高）。
SOURCE_PRIORITY: dict[str, int] = {"nvd": 0, "cnvd": 1}

# 进入 canonical 的最小样本数；不足时标记 insufficient_data，不做无依据排名。
MIN_SAMPLES: int = 2

# 预声明的技术栈 / 行业画像，用于相关性匹配（仅示例）。
RELEVANCE_PROFILE: set[str] = {"vendor:widget", "vendor:core", "vendor:exporter", "vendor:db"}

# 完整性评估的必需字段（存在率与有效率分开统计）。
REQUIRED_FIELDS: list[str] = ["title", "description", "cvss", "cwe", "references"]

_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
_CWE_RE = re.compile(r"^CWE-\d+$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def is_cve(value) -> bool:
    """判断字符串是否为合法 CVE 编号。"""
    return isinstance(value, str) and bool(_CVE_RE.match(value))


def is_cwe(value) -> bool:
    return isinstance(value, str) and bool(_CWE_RE.match(value))


def is_url(value) -> bool:
    return isinstance(value, str) and bool(_URL_RE.match(value))
