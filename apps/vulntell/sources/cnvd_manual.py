"""CNVD 官方人工下载文件导入适配器。

用户在 CNVD 官方页面完成登录/验证码并下载 CSV、JSON（或 UTF-8 文本）后，
VulnTell 只读取本地文件；不会访问下载链接、绕过 WAF 或抓取详情页。
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .errors import SourceError, SourceErrorKind
from .protocol import SourcePage, SourceRecord, SourceRequest

_CVE_PREFIX = "CVE-"


def _normalize_published_date(value: Any) -> Optional[str]:
    """将人工下载文件中的发布日期标准化为 ISO-8601；失败返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # 常见：2025-03-01 / 2025/03/01 / 20250301
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # 已是完整 ISO 时间则直接透传
    try:
        from datetime import datetime as _dt
        parsed = _dt.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class CNVDManualConfig:
    path: Path
    page_size: int = 100
    max_bytes: int = 50 * 1024 * 1024


_ALIASES = {
    "cnvdId": ("cnvdId", "CNVD编号", "CNVD ID", "cnvd_id"),
    "cveId": ("cveId", "CVE编号", "CVE ID", "cve_id"),
    "title": ("title", "漏洞名称", "漏洞标题", "name"),
    "level": ("level", "危害级别", "severity"),
    "type": ("type", "漏洞类型"),
    "publishedDate": ("publishedDate", "发布日期", "发布时间", "publish_date"),
    "source": ("source", "来源", "厂商"),
}


class CNVDManualFileSource:
    source = "cnvd"

    def __init__(self, config: CNVDManualConfig) -> None:
        if not 1 <= config.page_size <= 1000:
            raise ValueError("page_size must be 1-1000")
        self.config = config
        self._records: Optional[list[SourceRecord]] = None
        self.file_sha256 = ""

    def _load(self) -> list[SourceRecord]:
        if self._records is not None:
            return self._records
        path = self.config.path
        try:
            size = path.stat().st_size
            if size > self.config.max_bytes:
                raise ValueError(f"file exceeds {self.config.max_bytes} bytes")
            raw = path.read_bytes()
            self.file_sha256 = hashlib.sha256(raw).hexdigest()
            text = raw.decode("utf-8-sig")
            if path.suffix.lower() == ".json":
                data = json.loads(text)
                rows = data.get("records", data) if isinstance(data, dict) else data
            else:
                rows = list(csv.DictReader(text.splitlines()))
            if not isinstance(rows, list):
                raise ValueError("expected a JSON array or records list")
            out: list[SourceRecord] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                norm: dict[str, Any] = {}
                for key, aliases in _ALIASES.items():
                    for alias in aliases:
                        if alias in row and row[alias] not in (None, ""):
                            norm[key] = row[alias]
                            break
                record_id = str(norm.get("cnvdId", "")).strip()
                if not record_id:
                    continue
                # Canonical 字段：让 domain normalize / COSV mapper 能消费
                cve_raw = str(norm.get("cveId") or "").strip()
                cve_id = cve_raw if cve_raw.upper().startswith(_CVE_PREFIX) else None
                published_iso = _normalize_published_date(norm.get("publishedDate"))
                payload = dict(norm)
                payload.update({
                    "id": record_id,
                    "cve_id": cve_id,
                    "title": norm.get("title") or record_id,
                    "description": norm.get("title"),
                    "aliases": [cve_id] if cve_id else [],
                    "cnvd_level": norm.get("level"),
                    "cnvd_type": norm.get("type"),
                    "published_at": published_iso,
                    "modified_at": published_iso,
                    "import_sha256": self.file_sha256,
                })
                out.append(SourceRecord(record_id, payload, {
                    "source": "cnvd", "import_mode": "manual_download",
                    "file_sha256": self.file_sha256,
                    "import_sha256": self.file_sha256,
                    "published_at": published_iso,
                }))
            self._records = out
            return out
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    async def fetch_page(self, request: SourceRequest, cursor: Optional[str] = None) -> SourcePage | SourceError:
        try:
            rows = self._load()
        except FileNotFoundError:
            return SourceError("cnvd", SourceErrorKind.NOT_FOUND, "manual download file not found", False)
        except Exception as exc:
            return SourceError("cnvd", SourceErrorKind.INVALID_RESPONSE, f"invalid manual file: {exc}", False)
        start = int(cursor or "0") if (cursor or "0").isdigit() else -1
        if start < 0:
            return SourceError("cnvd", SourceErrorKind.INVALID_RESPONSE, "invalid cursor", False)
        size = min(request.page_size, self.config.page_size)
        page = rows[start:start + size]
        nxt = str(start + size) if start + size < len(rows) else None
        return SourcePage(tuple(page), nxt, nxt is not None, start // size, "cnvd", datetime.now(timezone.utc), request.request_fingerprint)
