"""Build a reproducible GitHub Advisory (GHSA) mirror batch from OSV bulk data."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from apps.vulntell.batch.manifest import create_batch_manifest, save_manifest, calculate_content_hash
from apps.vulntell.cosv.schema import validate_cosv_record
from apps.vulntell.cosv.serializer import serialize_cosv_to_file
from apps.vulntell.cosv import batch_observations_to_cosv
from apps.vulntell.domain.models import RawSourceRecord
from apps.vulntell.domain.normalize import normalize_record
from magent.checkpoint.models import canonical_json, checksum_of

START = datetime(2024, 9, 10, tzinfo=timezone.utc)
END = datetime(2026, 9, 15, tzinfo=timezone.utc)
VERSION = "2024-09-10_2026-09-15"
SRC = Path("deliveries/live-2y-20260910/osv/batch-20260910T000000Z/records.cosv.jsonl")
OUT = Path("deliveries/live-2y-20260910/github_advisory/batch-20260910T000000Z")

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "records.cosv.jsonl"
    if target.exists(): target.unlink()
    count = 0
    seen = set()
    issues = []
    with SRC.open(encoding="utf-8") as stream:
        for line in stream:
            try: item = json.loads(line)
            except json.JSONDecodeError: continue
            aliases = item.get("aliases", []) or []
            ghsa = next((a for a in aliases if isinstance(a, str) and a.startswith("GHSA-")), None)
            if not ghsa: ghsa = (item.get("database_specific") or {}).get("source_id")
            if not isinstance(ghsa, str) or not ghsa.startswith("GHSA-") or ghsa in seen: continue
            stamp = item.get("modified") or item.get("published")
            try:
                dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) if stamp else None
                if dt and dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                if dt and not (START <= dt.astimezone(timezone.utc) < END): continue
            except ValueError: pass
            seen.add(ghsa)
            payload = dict(item)
            payload.update({"id": ghsa, "ghsa_id": ghsa, "cve_id": next((a for a in aliases if str(a).startswith("CVE-")), None),
                            "title": item.get("summary") or ghsa, "description": item.get("details") or item.get("summary") or ghsa,
                            "published_at": item.get("published"), "modified_at": item.get("modified")})
            raw = RawSourceRecord(source="github_advisory", record_id=ghsa, observed_at=datetime.now(timezone.utc),
                                  dataset_id="github-advisory-cve", dataset_version=VERSION, payload=payload,
                                  payload_hash=checksum_of(canonical_json(payload)))
            obs, qi = normalize_record(raw); issues.extend(qi)
            docs, mi = batch_observations_to_cosv([obs]); issues.extend(mi)
            for doc in docs:
                ok, errors = validate_cosv_record(doc.model_dump(mode="json"))
                if ok:
                    serialize_cosv_to_file(doc, target, mode="a"); count += 1
                else: issues.append({"id": doc.id, "type": "cosv_schema_error", "errors": errors})
    manifest = create_batch_manifest("osv-ghsa-mirror", "github_advisory", VERSION, START.isoformat(), END.isoformat(), count,
        calculate_content_hash(target), "GitHub-terms/OSV-mirror", page_count=1, fetched_record_count=count,
        truncated=False, collection_complete=True)
    save_manifest(manifest, OUT)
    (OUT / "quality.json").write_text(json.dumps({"method":"OSV GHSA mirror fallback","issues":issues},ensure_ascii=False,default=str),encoding="utf-8")
    print(json.dumps(manifest.model_dump(mode="json"),ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
