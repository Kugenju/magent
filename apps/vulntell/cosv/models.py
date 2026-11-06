"""COSV-Schema v1.0.0 数据模型。"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COSV_SCHEMA_VERSION = "1.0.0"
SUPPORTED_COSV_SCHEMA_VERSIONS = {COSV_SCHEMA_VERSION}

def _is_utc_timestamp(value: str) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"): return False
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError: return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None

class VersionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    introduced: Optional[str] = None; fixed: Optional[str] = None
    last_affected: Optional[str] = None; limit: Optional[str] = None
    @model_validator(mode="after")
    def exactly_one_endpoint(self):
        if sum(v is not None for v in (self.introduced,self.fixed,self.last_affected,self.limit)) != 1:
            raise ValueError("a range event must contain exactly one endpoint")
        return self

class VersionRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str; repo: Optional[str] = None
    events: list[VersionEvent] = Field(default_factory=list)
    database_specific: Optional[dict[str, Any]] = None
    @field_validator("type")
    @classmethod
    def normalize_type(cls, v): return v.upper() if v else v
    @model_validator(mode="after")
    def valid_type(self):
        if self.type is not None and self.type not in {"ECOSYSTEM","GIT","SEMVER"}: raise ValueError("invalid range type")
        return self

class Package(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ecosystem: str; name: str; purl: Optional[str] = None; language: Optional[str] = None
    repository: Optional[str] = None; introduced_commits: list[str] = Field(default_factory=list)
    fixed_commits: list[str] = Field(default_factory=list); home_page: Optional[str] = None; edition: Optional[str] = None
class Affected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: Package; ranges: list[VersionRange] = Field(default_factory=list); versions: list[str] = Field(default_factory=list)
class Severity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str; score: Optional[str] = None; level: Optional[str] = None; score_num: Optional[str] = None
class SeverityType(str, Enum):
    CVSS_V2="CVSS_V2"; CVSS_V3="CVSS_V3"; CVSS_V31="CVSS_V31"; CVSS_V4="CVSS_V4"
class ReferenceType(str, Enum):
    ADVISORY="advisory"; WEB="web"; FIX="patch"; REPORT="report"; PACKAGE="package"
class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str; url: str
class TimeLineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str; value: str
    @field_validator("value")
    @classmethod
    def valid_value(cls,v):
        if not _is_utc_timestamp(v): raise ValueError("time_line.value must be RFC3339 UTC")
        return v
class PatchDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patch_url: Optional[str]=None; issue_url: Optional[str]=None; main_language: Optional[str]=None; author: Optional[str]=None; commiter: Optional[str]=None
    branches: list[str]=Field(default_factory=list); tags: list[str]=Field(default_factory=list)
class Contributor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org: Optional[str]=None; name: Optional[str]=None; email: Optional[str]=None; contributions: Optional[str]=None
class Credit(BaseModel):
    name: str
    contact: list[str] = Field(default_factory=list)
class DatabaseSpecific(BaseModel):
    model_config = ConfigDict(extra="allow")
class COSVDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = COSV_SCHEMA_VERSION; id: str
    aliases: list[str]=Field(default_factory=list); related: list[str]=Field(default_factory=list)
    cwe_ids: list[str]=Field(default_factory=list); cwe_names: list[str]=Field(default_factory=list)
    time_line: list[TimeLineEvent]=Field(default_factory=list); summary: Optional[str]=None; details: Optional[str]=None
    references: list[Reference]=Field(default_factory=list); published: Optional[str]=None; withdrawn: Optional[str]=None; modified: str
    severity: list[Severity]=Field(default_factory=list); affected: list[Affected]=Field(default_factory=list)
    patches_detail: list[PatchDetail]=Field(default_factory=list); contributors: list[Contributor]=Field(default_factory=list)
    confirm_type: Optional[str]=None; database_specific: Optional[dict[str,Any]]=None; credits: list[str]=Field(default_factory=list)
    @field_validator("id")
    @classmethod
    def valid_id(cls,v):
        if not isinstance(v,str) or not v.strip(): raise ValueError("id must be a non-empty string")
        return v
    @field_validator("schema_version")
    @classmethod
    def valid_schema(cls,v):
        if v not in SUPPORTED_COSV_SCHEMA_VERSIONS: raise ValueError(f"unsupported COSV schema_version: {v}")
        return v
    @field_validator("modified","published","withdrawn")
    @classmethod
    def valid_time(cls,v):
        if v is not None and not _is_utc_timestamp(v): raise ValueError("timestamp must be RFC3339 UTC with Z")
        return v
    @field_validator("confirm_type")
    @classmethod
    def valid_confirm(cls,v):
        if v is not None and v not in {"manual_confirmed","algorithm_confirmed","double_confirmed"}: raise ValueError("invalid confirm_type")
        return v
    def model_dump_stable(self): return self.model_dump(mode="json", exclude_none=True, exclude_unset=True)
