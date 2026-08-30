"""VulnTell 应用配置（阶段 1，Task 1.1）。

不可变（frozen）配置对象，统一 CLI 与未来 API 的输入。CLI 参数转换为配置只做
解析与校验，不执行任何副作用；fixture 路径不依赖当前工作目录。

约束：
- 不保存 API key 明文或原始漏洞文本；
- 未知来源、空 run id、非法 checkpoint 组合应尽早报错；
- 所有路径使用 ``pathlib.Path``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import AbstractSet, FrozenSet, Optional

_KNOWN_SOURCES: FrozenSet[str] = frozenset({"nvd", "cnvd"})


@dataclass(frozen=True)
class VulnTellConfig:
    """一次 VulnTell 运行的只读配置。"""

    db: str = ":memory:"
    checkpoint: str = ":memory:"
    run_id: str = "vulntell-demo-run"
    no_llm: bool = False
    json_output: bool = False
    faulty_sources: FrozenSet[str] = field(default_factory=frozenset)
    trace_prefix: Optional[str] = None
    resume: bool = False

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id 不能为空")
        unknown = {s for s in self.faulty_sources if s not in _KNOWN_SOURCES}
        if unknown:
            raise ValueError(f"未知来源（不在 {sorted(_KNOWN_SOURCES)}）：{sorted(unknown)}")
        if self.checkpoint == ":memory:" and self.resume:
            raise ValueError("resume 不能与 :memory: checkpoint 同时使用（无持久化可恢复）")

    @property
    def fixture_dir(self) -> Path:
        """fixture 路径固定（apps.vulntell.fixtures），不依赖当前工作目录。"""
        from apps.vulntell import FIXTURE_DIR

        return FIXTURE_DIR

    @classmethod
    def from_cli_args(
        cls,
        *,
        db: str = ":memory:",
        checkpoint: str = ":memory:",
        run_id: str = "vulntell-demo-run",
        resume: bool = False,
        no_llm: bool = False,
        json_output: bool = False,
        faulty: Optional[list[str]] = None,
        trace: Optional[str] = None,
    ) -> "VulnTellConfig":
        """从 CLI 参数构建配置（仅解析与校验，无副作用）。"""
        return cls(
            db=db,
            checkpoint=checkpoint,
            run_id=run_id,
            no_llm=no_llm,
            json_output=json_output,
            faulty_sources=frozenset(faulty or ()),
            trace_prefix=trace,
            resume=resume,
        )
