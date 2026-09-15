"""Stream MSRC CVRF bulletins into one auditable COSV batch."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from apps.vulntell.batch.manifest import create_batch_manifest, save_manifest, calculate_content_hash
from apps.vulntell.cosv.schema import validate_cosv_record
from apps.vulntell.cosv.serializer import serialize_cosv_to_file
from apps.vulntell.cosv import batch_observations_to_cosv
from apps.vulntell.domain.models import RawSourceRecord
from apps.vulntell.domain.normalize import normalize_record
from apps.vulntell.sources.msrc import MSRCAdapter
from magent.checkpoint.models import canonical_json, checksum_of

START = datetime(2024, 9, 10, tzinfo=timezone.utc)
END = datetime(2026, 9, 15, tzinfo=timezone.utc)
OUT = Path("deliveries/live-2y-20260910/msrc/batch-20260910T000000Z")
VERSION = "2024-09-10_2026-09-15"


def in_window(value: str | None) -> bool:
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return START <= dt.astimezone(timezone.utc) < END
    except ValueError:
        return False


async def main() -> None:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
    timeout = httpx.Timeout(90.0, connect=30.0)
    OUT.mkdir(parents=True, exist_ok=True)
    records_path = OUT / "records.cosv.jsonl"
    if records_path.exists():
        records_path.unlink()
    total = 0
    pages = 0
    issues = []
    async with httpx.AsyncClient(proxy=proxy, timeout=timeout, limits=limits,
                                 headers={"User-Agent": "VulnTell-research/1.0"}) as client:
        index = await client.get("https://api.msrc.microsoft.com/cvrf/v3.0/updates")
        index.raise_for_status()
        updates = index.json().get("value", [])
        selected = []
        for item in updates:
            stamp = item.get("InitialReleaseDate") or item.get("CurrentReleaseDate")
            if in_window(stamp):
                selected.append(item)
        for item in sorted(selected, key=lambda x: x.get("InitialReleaseDate", "")):
            url = item.get("CvrfUrl")
            if not url:
                continue
            try:
                response = await client.get(url)
                response.raise_for_status()
                parsed = MSRCAdapter._parse_cvrf_xml(response.text)
                raw = []
                observed = datetime.now(timezone.utc)
                for row in parsed.get("value", []):
                    raw.append(RawSourceRecord(
                        source="msrc", record_id=row["id"], observed_at=observed,
                        dataset_id="msrc-cve", dataset_version=VERSION,
                        payload=row, payload_hash=checksum_of(canonical_json(row))))
                observations = []
                for entry in raw:
                    obs, qi = normalize_record(entry)
                    observations.append(obs)
                    issues.extend(qi)
                docs, map_issues = batch_observations_to_cosv(observations)
                issues.extend(map_issues)
                for doc in docs:
                    ok, errors = validate_cosv_record(doc.model_dump(mode="json"))
                    if ok:
                        serialize_cosv_to_file(doc, records_path, mode="a")
                        total += 1
                    else:
                        issues.append({"source_record_id": doc.id, "type": "cosv_schema_error", "errors": errors})
                pages += 1
                print(f"[{item.get('ID')}] records={len(docs)} total={total}", flush=True)
            except Exception as exc:
                issues.append({"bulletin": item.get("ID"), "type": "fetch_error", "error": repr(exc)})
                print(f"[{item.get('ID')}] ERROR {exc!r}", flush=True)
    manifest = create_batch_manifest("live-2y-stream", "msrc", VERSION,
        START.isoformat(), END.isoformat(), total,
        calculate_content_hash(records_path), "Microsoft-terms",
        page_count=pages, fetched_record_count=total, truncated=False,
        collection_complete=True)
    save_manifest(manifest, OUT)
    (OUT / "quality.json").write_text(json.dumps({"issues": issues, "method": "streamed_cvrf"}, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
