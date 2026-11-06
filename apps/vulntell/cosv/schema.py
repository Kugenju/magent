"""VulnTell COSV JSON Schema 校验（阶段 A）。

提供 validate_cosv_file() 和 validate_cosv_record() API。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from apps.vulntell.cosv.models import COSVDocument, SUPPORTED_COSV_SCHEMA_VERSIONS

# RFC 3339 UTC 时间格式
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
)

# COSV-Schema 1.0.0 JSON Schema
COSV_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "COSV Document",
    "description": "Chinese Open Source Vulnerability Format",
    "type": "object",
    "required": ["schema_version", "id", "modified"],
    "properties": {
        "schema_version": {
            "type": "string",
            "description": "COSV schema version",
            "const": "1.0.0",
        },
        "id": {
            "type": "string",
            "minLength": 1,
            "description": "Global unique stable ID (CVE preferred)",
        },
        "modified": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$",
            "description": "RFC 3339 UTC timestamp",
        },
        "published": {
            "type": ["string", "null"],
            "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$",
        },
        "aliases": {
            "type": "array",
            "items": {"type": "string"},
        },
        "summary": {
            "type": ["string", "null"],
        },
        "details": {
            "type": ["string", "null"],
        },
        "affected": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["package"],
                "properties": {
                    "package": {
                        "type": "object",
                        "required": ["name", "ecosystem"],
                        "properties": {
                            "name": {"type": "string"},
                            "ecosystem": {"type": "string"},
                        },
                    },
                    "ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "events": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "introduced": {"type": "string"},
                                            "fixed": {"type": "string"},
                                            "last_affected": {"type": "string"},
                                            "limit": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "versions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "severity": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "score": {"type": ["string", "null"]},
                    "vector": {"type": ["string", "null"]},
                },
            },
        },
        "references": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "url"],
                "properties": {
                    "type": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
        "credits": {
            "type": "array",
            "items": {"type": "string"},
        },
        "database_specific": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "source_id": {"type": "string"},
            },
            "additionalProperties": True,
        },
    },
    "additionalProperties": True,
}


def validate_cosv_record(record: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验单条 COSV 记录。

    Args:
        record: 待校验的 COSV 记录字典

    Returns:
        (is_valid, errors) 元组
    """
    errors = []

    # 1. 基础字段校验
    required_fields = ["schema_version", "id", "modified"]
    for field in required_fields:
        if field not in record or not record[field]:
            errors.append(f"missing required field: {field}")

    if errors:
        return False, errors

    # 2. schema_version 校验
    if record.get("schema_version") not in SUPPORTED_COSV_SCHEMA_VERSIONS:
        errors.append(f"invalid schema_version: {record.get('schema_version')}")

    # 3. id 校验
    if not isinstance(record["id"], str) or not record["id"].strip():
        errors.append("id must be a non-empty string")

    # 4. modified 时间格式校验
    modified = record.get("modified", "")
    if not _RFC3339_PATTERN.match(modified):
        errors.append(f"modified must be RFC 3339 UTC: {modified}")

    # 5. published 时间格式校验（可选）
    published = record.get("published")
    if published is not None and published != "":
        if not _RFC3339_PATTERN.match(published):
            errors.append(f"published must be RFC 3339 UTC: {published}")

    withdrawn = record.get("withdrawn")
    if withdrawn is not None and withdrawn != "":
        if not _RFC3339_PATTERN.match(withdrawn):
            errors.append(f"withdrawn must be RFC 3339 UTC: {withdrawn}")

    # 6. affected 数组校验
    affected = record.get("affected", [])
    if not isinstance(affected, list):
        errors.append("affected must be an array")
    else:
        for i, item in enumerate(affected):
            if not isinstance(item, dict):
                errors.append(f"affected[{i}] must be an object")
                continue
            package = item.get("package")
            if not package or not isinstance(package, dict):
                errors.append(f"affected[{i}].package is required")
            else:
                if "name" not in package or not package["name"]:
                    errors.append(f"affected[{i}].package.name is required")
                if "ecosystem" not in package or not package["ecosystem"]:
                    errors.append(f"affected[{i}].package.ecosystem is required")
            for j, version_range in enumerate(item.get("ranges", []) or []):
                if not isinstance(version_range, dict):
                    continue
                range_type = version_range.get("type")
                if range_type and str(range_type).upper() not in {"ECOSYSTEM", "GIT", "SEMVER"}:
                    errors.append(f"affected[{i}].ranges[{j}].type is invalid")
                for k, event in enumerate(version_range.get("events", []) or []):
                    if not isinstance(event, dict):
                        continue
                    endpoints = [x for x in ("introduced", "fixed", "last_affected", "limit") if event.get(x) is not None]
                    if len(endpoints) != 1:
                        errors.append(f"affected[{i}].ranges[{j}].events[{k}] must contain exactly one endpoint")

    # 7. severity 数组校验
    severity = record.get("severity", [])
    if not isinstance(severity, list):
        errors.append("severity must be an array")
    else:
        valid_severity_types = ["CVSS_V2", "CVSS_V3", "CVSS_V31", "CVSS_V4"]
        for i, item in enumerate(severity):
            if not isinstance(item, dict):
                errors.append(f"severity[{i}] must be an object")
                continue
            stype = item.get("type")
            if not isinstance(stype, str) or not stype.strip():
                errors.append(f"severity[{i}].type must be a non-empty string")
            if item.get("score_num") is not None and not isinstance(item.get("score_num"), str):
                errors.append(f"severity[{i}].score_num must be a string")

    # 8. references 数组校验
    references = record.get("references", [])
    if not isinstance(references, list):
        errors.append("references must be an array")
    else:
        valid_ref_types = ["ADVISORY", "WEB", "FIX", "REPORT", "PACKAGE"]
        for i, item in enumerate(references):
            if not isinstance(item, dict):
                errors.append(f"references[{i}] must be an object")
                continue
            rtype = item.get("type")
            if not isinstance(rtype, str) or not rtype.strip():
                errors.append(f"references[{i}].type must be a non-empty string")
            url = item.get("url")
            if not url or not isinstance(url, str):
                errors.append(f"references[{i}].url is required")

    confirm_type = record.get("confirm_type")
    if confirm_type is not None and confirm_type not in {
        "manual_confirmed", "algorithm_confirmed", "double_confirmed"
    }:
        errors.append("confirm_type is invalid")

    # 9. Pydantic 模型校验
    try:
        COSVDocument(**record)
    except ValidationError as e:
        for err in e.errors():
            errors.append(f"pydantic: {err.get('msg', '')}")

    return len(errors) == 0, errors


def validate_cosv_file(file_path: str | Path) -> tuple[bool, list[dict[str, Any]]]:
    """校验 COSV JSONL 文件。

    Args:
        file_path: COSV JSONL 文件路径

    Returns:
        (is_valid, validation_results) 元组
        validation_results 列表中每个元素包含 {"line": int, "valid": bool, "errors": list[str]}
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return False, [{"line": 0, "valid": False, "errors": [f"file not found: {file_path}"]}]

    results = []
    all_valid = True

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                results.append({
                    "line": line_num,
                    "valid": False,
                    "errors": [f"JSON decode error: {e}"],
                })
                all_valid = False
                continue

            is_valid, errors = validate_cosv_record(record)
            results.append({
                "line": line_num,
                "valid": is_valid,
                "errors": errors,
            })
            if not is_valid:
                all_valid = False

    return all_valid, results
