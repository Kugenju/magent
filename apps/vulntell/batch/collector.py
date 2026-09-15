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
from apps.vulntell.cosv.schema import validate_cosv_record
from .manifest import create_batch_manifest, save_manifest

async def collect_adapter(
    adapter,
    request,
    output_dir: str | Path,
    *,
    collector_id="local",
    license="unknown",
    max_records: int | None = None,
):
    """采集完整分页并写出 COSV 批次。

    ``max_records`` 仅用于明确的抽样/烟测；默认 ``None``，不再隐式限制为
    100 条。达到显式上限时，manifest 会标记 ``truncated=true``，避免把抽样
    结果误当成完整窗口数据。
    """
    out=Path(output_dir); out.mkdir(parents=True, exist_ok=True); raw=[]; cursor=None; page_count=0; truncated=False; next_cursor=None
    while True:
        page=await adapter.fetch_page(request,cursor)
        if not hasattr(page,"records"): raise RuntimeError(getattr(page,"message", "source error"))
        page_count += 1
        for rec in page.records:
            raw.append(RawSourceRecord(source=request.source, record_id=rec.source_record_id,
                observed_at=page.observed_at, dataset_id=request.dataset_id,
                dataset_version=request.dataset_version, payload=rec.payload,
                payload_hash=checksum_of(canonical_json(rec.payload))))
        if not page.has_more:
            break
        if max_records is not None and len(raw) >= max_records:
            truncated = True
            next_cursor = page.next_cursor
            break
        if not page.next_cursor:
            truncated = True
            break
        cursor=page.next_cursor
        next_cursor = cursor
    observations=[]; issues=[]
    if max_records is not None:
        raw = raw[:max_records]
    for item in raw:
        obs, qi=normalize_record(item); observations.append(obs); issues.extend(qi)
    docs, map_issues=batch_observations_to_cosv(observations); issues.extend(map_issues)
    # Do not deliver a batch whose normalized documents fail the COSV contract.
    valid_docs = []
    for doc in docs:
        ok, errors = validate_cosv_record(doc.model_dump(mode="json"))
        if ok:
            valid_docs.append(doc)
        else:
            issues.append({"source": request.source, "source_record_id": doc.id,
                           "type": "cosv_schema_error", "errors": errors})
    docs = valid_docs
    records=out/"records.cosv.jsonl"
    if records.exists(): records.unlink()
    records.touch()
    for doc in docs: serialize_cosv_to_file(doc, records, mode="a")
    from .manifest import calculate_content_hash
    manifest=create_batch_manifest(collector_id, request.source, request.dataset_version,
        request.window_start.isoformat(), request.window_end.isoformat(), len(docs), calculate_content_hash(records), license,
        page_count=page_count, fetched_record_count=len(raw), truncated=truncated,
        next_cursor=next_cursor, collection_complete=not truncated)
    save_manifest(manifest,out)
    (out/"quality.json").write_text(json.dumps({"issues":issues},ensure_ascii=False,default=str),encoding="utf-8")
    return manifest, docs
