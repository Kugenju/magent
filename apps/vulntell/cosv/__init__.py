"""VulnTell COSV 模块（阶段 A：COSV 核心落盘）。

COSV (Chinese Open Source Vulnerability format) 是所有来源进入 VulnTell 的最终漏洞记录格式。
来源原始字段只允许保存在受控的原始归档区，不得直接作为业务查询格式。

模块提供：
- COSV 数据模型（Pydantic）
- JSON Schema 校验
- SourceObservation → COSV 映射
- 稳定序列化和内容哈希
- 版本迁移入口

约束：
- schema_version 固定为 1.0
- 时间统一 RFC3339 UTC
- 数组去重并稳定排序
- 不得把 API key、Cookie、原始响应写入 COSV
"""

from apps.vulntell.cosv.models import (
    Affected,
    COSVDocument,
    Credit,
    DatabaseSpecific,
    Package,
    Reference,
    Severity,
    VersionRange,
)
from apps.vulntell.cosv.schema import validate_cosv_file, validate_cosv_record
from apps.vulntell.cosv.serializer import content_hash, serialize_cosv
from apps.vulntell.cosv.mapper import observation_to_cosv, batch_observations_to_cosv

__all__ = [
    "COSVDocument",
    "Affected",
    "Package",
    "VersionRange",
    "Severity",
    "Reference",
    "Credit",
    "DatabaseSpecific",
    "validate_cosv_file",
    "validate_cosv_record",
    "serialize_cosv",
    "content_hash",
    "observation_to_cosv",
    "batch_observations_to_cosv",
]
