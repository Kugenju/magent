"""VulnTell COSV 数据模型（阶段 A）。

COSV (Chinese Open Source Vulnerability format) 文档结构，遵循 INTELLIGENCE_SOURCES.md 规范。

字段要求：
- schema_version: 必填，非空字符串；表示 COSV schema 版本
- id: 必填、全局唯一、稳定；优先使用 CVE-...，无 CVE 时使用来源稳定 ID
- modified: 必填，RFC 3339/ISO-8601 UTC 时间（带 Z）
- published: 有则为 RFC 3339 UTC 时间；未知时省略
- aliases: 可选字符串数组；放置 CVE、GHSA、CNVD 等跨库别名
- summary: 可选短标题，字符串；保留来源语言
- details: 可选详细描述，字符串
- affected: 可选数组；每项必须有 package（name、ecosystem），版本范围用 events
- severity: 可选数组；保存 CVSS 向量和评分类型
- references: 有则为数组；每项包含 type 和 url
- credits: 可选字符串数组；仅记录来源明确公开的致谢信息
- database_specific: 可选对象；仅放来源专属、非标准字段
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class VersionEvent(BaseModel):
    """版本事件：introduced、fixed、last_affected、limit。"""

    introduced: Optional[str] = None
    fixed: Optional[str] = None
    last_affected: Optional[str] = None
    limit: Optional[str] = None

    @field_validator("introduced", "fixed", "last_affected", "limit")
    @classmethod
    def validate_version(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not isinstance(v, str):
            raise ValueError("version must be a string")
        return v


class VersionRange(BaseModel):
    """版本范围：使用 events 语义。"""

    type: Optional[str] = None
    events: list[VersionEvent] = Field(default_factory=list)


class Package(BaseModel):
    """受影响包信息。"""

    name: str
    ecosystem: str


class Affected(BaseModel):
    """受影响条目。"""

    package: Package
    ranges: list[VersionRange] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)


class SeverityType(str, Enum):
    """严重性类型。"""

    CVSS_V2 = "CVSS_V2"
    CVSS_V3 = "CVSS_V3"
    CVSS_V31 = "CVSS_V31"
    CVSS_V4 = "CVSS_V4"


class Severity(BaseModel):
    """严重性信息。"""

    type: SeverityType
    score: Optional[str] = None
    vector: Optional[str] = None


class ReferenceType(str, Enum):
    """引用类型。"""

    ADVISORY = "ADVISORY"
    WEB = "WEB"
    FIX = "FIX"
    REPORT = "REPORT"
    PACKAGE = "PACKAGE"


class Reference(BaseModel):
    """引用信息。"""

    type: ReferenceType
    url: str


class Credit(BaseModel):
    """致谢信息。"""

    name: str
    contact: list[str] = Field(default_factory=list)


class DatabaseSpecific(BaseModel):
    """来源专属字段。"""

    class Config:
        extra = "allow"

    source: Optional[str] = None
    source_id: Optional[str] = None
    import_batch: Optional[str] = None
    import_sha256: Optional[str] = None
    cnvd_level: Optional[str] = None
    kev_date_added: Optional[str] = None
    kev_due_date: Optional[str] = None
    kev_ransomware_use: Optional[bool] = None
    source_version_text: Optional[str] = None


class COSVDocument(BaseModel):
    """COSV 文档结构。

    遵循 INTELLIGENCE_SOURCES.md 规范的完整 COSV 文档。
    """

    schema_version: str = "1.0"
    id: str
    modified: str  # RFC 3339 UTC
    published: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    details: Optional[str] = None
    affected: list[Affected] = Field(default_factory=list)
    severity: list[Severity] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    credits: list[str] = Field(default_factory=list)
    database_specific: Optional[DatabaseSpecific] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v:
            raise ValueError("id must not be empty")
        return v

    @field_validator("modified")
    @classmethod
    def validate_modified(cls, v: str) -> str:
        # 验证 RFC 3339 UTC 格式
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("modified must be UTC (with Z suffix)")
        except ValueError as e:
            raise ValueError(f"modified must be RFC 3339 UTC: {e}")
        return v

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, v: list[str]) -> list[str]:
        # 去重并稳定排序
        return sorted(set(v))

    @field_validator("references")
    @classmethod
    def validate_references(cls, v: list[Reference]) -> list[Reference]:
        # 去重并稳定排序
        seen = set()
        unique = []
        for ref in v:
            key = (ref.type, ref.url)
            if key not in seen:
                seen.add(key)
                unique.append(ref)
        return sorted(unique, key=lambda x: (x.type, x.url))

    def model_dump_stable(self) -> dict[str, Any]:
        """稳定序列化：保证相同输入产生相同内容哈希。"""
        return self.model_dump(
            mode="json",
            exclude_none=True,
            exclude_unset=True,
        )
