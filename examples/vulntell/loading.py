"""加载冻结的离线 fixture 与数据集元数据（阶段 7）。

加载器是确定性的：同一文件始终得到相同 ``RawSourceRecord``（payload hash 用
canonical_json 计算，与字段顺序无关）。默认 CLI 只使用 fixture，从不联网。
"""

from __future__ import annotations

import json
import pathlib

from magent.checkpoint.models import canonical_json, checksum_of

from .models import DatasetMeta, RawSourceRecord


def load_dataset_meta(path: str | pathlib.Path) -> DatasetMeta:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return DatasetMeta(**data)


def load_fixture(
    path: str | pathlib.Path,
    *,
    observed_at,
    dataset_id: str = "vulntell-demo",
    dataset_version: str = "demo",
) -> list[RawSourceRecord]:
    """读取一个来源 fixture，返回原始记录列表。

    ``observed_at`` 是系统观测时间（UTC），由调用方统一传入（默认取窗口上界），
    不参与 payload hash，从而保证 fixture 内容决定 hash。
    """
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    source = data["source"]
    records = data.get("records", [])
    out: list[RawSourceRecord] = []
    for rec in records:
        payload_hash = checksum_of(canonical_json(rec))
        out.append(
            RawSourceRecord(
                source=source,
                record_id=rec["record_id"],
                observed_at=observed_at,
                dataset_id=data.get("dataset_id", dataset_id),
                dataset_version=data.get("dataset_version", dataset_version),
                payload=rec,
                payload_hash=payload_hash,
            )
        )
    return out
