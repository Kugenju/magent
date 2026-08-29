"""阶段 8 参考框架对比记录（Task 6）。

先完成设计/API/语义对比，再决定哪些参考框架可运行。为每个框架建立隔离记录，禁止污染
``src/magent``。仅报告同场景可比结果；不可比项保留原因、版本与环境信息，绝不输出排名。
参考框架依赖不在仓库内，不可用/版本冲突/网络不可用时，不阻塞 ``magent`` 本地 benchmark，
但记录缺失项。
"""

from __future__ import annotations

import importlib
import platform
import sys
from typing import Any, Optional

from pydantic import BaseModel, Field


class ReferenceRecord(BaseModel):
    """单个参考框架的对比记录。"""

    framework: str
    installed: bool = False
    version: Optional[str] = None
    status: str = "not_comparable"  # comparable | not_comparable
    reason: str = ""
    config: Optional[dict[str, Any]] = None
    environment: dict[str, Any] = Field(default_factory=dict)


_REFERENCE_FRAMEWORKS = ["langgraph", "autogen", "crewai"]


def _env() -> dict[str, Any]:
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.platform(),
    }


def _try_version(name: str) -> Optional[str]:
    try:
        from importlib import metadata

        return metadata.version(name)
    except Exception:  # noqa: BLE001
        return None


def collect_reference_comparison() -> list[ReferenceRecord]:
    """收集参考框架版本/环境/配置记录；默认全部 ``not_comparable``。"""
    records: list[ReferenceRecord] = []
    env = _env()
    for name in _REFERENCE_FRAMEWORKS:
        rec = ReferenceRecord(framework=name, environment=env)
        try:
            importlib.import_module(name)
            rec.installed = True
            rec.version = _try_version(name)
            # 已安装也不在此离线脚本中运行等价实验；等价条件未建立，仍标记不可比。
            rec.status = "not_comparable"
            rec.reason = "installed but equivalence not established in offline benchmark; no ranking emitted"
        except Exception:  # noqa: BLE001 - ImportError or any load failure
            rec.installed = False
            rec.status = "not_comparable"
            rec.reason = "dependency not installed or version conflict; not blocking local benchmark"
        records.append(rec)
    return records


def to_comparison_report(records: list[ReferenceRecord]) -> dict:
    """生成对比报告；明确不包含任何排名。"""
    comparable = [r for r in records if r.status == "comparable"]
    return {
        "comparable": bool(comparable),
        "ranking": None,  # 永不输出排名
        "records": [r.model_dump() for r in records],
        "note": "no ranking produced; comparable frameworks require an explicit equivalence protocol",
    }
