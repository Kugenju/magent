"""VulnTell COSV 序列化与内容哈希（阶段 A）。

提供 serialize_cosv() 和 content_hash() API。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Union

from apps.vulntell.cosv.models import COSVDocument


def content_hash(data: Union[COSVDocument, dict[str, Any], str]) -> str:
    """计算内容的 SHA-256 哈希。

    对于 COSVDocument，使用稳定序列化。
    对于字典，使用稳定 JSON 序列化。
    对于字符串，直接计算哈希。

    Args:
        data: 要计算哈希的数据

    Returns:
        SHA-256 哈希值（十六进制）
    """
    if isinstance(data, COSVDocument):
        serialized = serialize_cosv(data)
    elif isinstance(data, dict):
        serialized = json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    elif isinstance(data, str):
        serialized = data
    else:
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def serialize_cosv(doc: COSVDocument) -> str:
    """将 COSVDocument 序列化为稳定的 JSON 字符串。

    约束：
    - UTF-8 编码
    - 稳定字段顺序（按字母排序）
    - 移除 None 值（但保留 schema_version）
    - 数组去重并稳定排序

    Args:
        doc: COSV 文档

    Returns:
        稳定 JSON 字符串
    """
    # 使用 model_dump_stable 获取稳定序列化
    data = doc.model_dump_stable()

    # 确保 schema_version 始终存在
    if "schema_version" not in data:
        data["schema_version"] = doc.schema_version

    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def serialize_cosv_to_file(
    doc: COSVDocument,
    file_path: str | Path,
    mode: str = "a",
) -> str:
    """将 COSVDocument 序列化并写入 JSONL 文件。

    Args:
        doc: COSV 文档
        file_path: 文件路径
        mode: 写入模式（"a" 追加，"w" 覆盖）

    Returns:
        写入的内容哈希
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = serialize_cosv(doc)

    with open(file_path, mode, encoding="utf-8") as f:
        f.write(serialized + "\n")

    return content_hash(serialized)


def deserialize_cosv(line: str) -> COSVDocument | None:
    """从 JSONL 行反序列化为 COSVDocument。

    Args:
        line: JSONL 行

    Returns:
        COSVDocument 或 None（解析失败）
    """
    try:
        data = json.loads(line.strip())
        return COSVDocument(**data)
    except Exception:
        return None


def read_cosv_file(file_path: str | Path) -> list[COSVDocument]:
    """读取 COSV JSONL 文件。

    Args:
        file_path: JSONL 文件路径

    Returns:
        COSVDocument 列表
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return []

    docs = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = deserialize_cosv(line)
            if doc:
                docs.append(doc)

    return docs
