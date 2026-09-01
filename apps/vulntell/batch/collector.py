"""将任意 SourcePage adapter 采集为可交换 COSV 批次。"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from magent.checkpoint.models import canonical_json, checksum_of
from apps.vulntell.domain.models import RawSourceRecord
from apps.vulntell.domain.normalize import normalize_record
from apps.vulntell.cosv import batch_observations_to_cosv
from apps.vulntell.cosv.serializer import serialize_cosv_to_file
from .manifest import create_batch_manifest, save_manifest

async def collect_adapter(adapter, request, output_dir: str|Path, *, collector_id="local", license="unknown"):
    out=Path(output_dir); out.mkdir(parents=True, exist_ok=True); raw=[]; cursor=None
    while True:
        page=await adapter.fetch_page(request,cursor)
        if not hasattr(page,"records"): raise RuntimeError(getattr(page,"message", "source error"))
        for rec in page.records:
            raw.append(RawSourceRecord(source=request.source, record_id=rec.source_record_id,
                observed_at=page.observed_at, dataset_id=request.dataset_id,
                dataset_version=request.dataset_version, payload=rec.payload,
                payload_hash=checksum_of(canonical_json(rec.payload))))
        if not page.has_more or len(raw)>=100: break
        cursor=page.next_cursor
    observations=[]; issues=[]
    for item in raw[:100]:
        obs, qi=normalize_record(item); observations.append(obs); issues.extend(qi)
    docs, map_issues=batch_observations_to_cosv(observations); issues.extend(map_issues)
    records=out/"records.cosv.jsonl"
    if records.exists(): records.unlink()
    for doc in docs: serialize_cosv_to_file(doc, records, mode="a")
    from .manifest import calculate_content_hash
    manifest=create_batch_manifest(collector_id, request.source, request.dataset_version,
        request.window_start.isoformat(), request.window_end.isoformat(), len(docs), calculate_content_hash(records), license)
    save_manifest(manifest,out)
    (out/"quality.json").write_text(json.dumps({"issues":issues},ensure_ascii=False,default=str),encoding="utf-8")
    return manifest, docs
