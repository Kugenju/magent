"""apps.vulntell 应用包（阶段 2）。

阶段 2 起，领域实现位于 apps.vulntell.domain 与 apps.vulntell.reporting，fixture
集中于 apps.vulntell.fixtures。本包暴露 FIXTURE_DIR 供配置与应用统一解析 fixture
路径（不依赖当前工作目录）。
"""

from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
