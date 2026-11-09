"""每日简报 CLI 入口：``python -m apps.vulntell.daily``（实现在 pipeline/daily.py）。"""

from apps.vulntell.pipeline.daily import DailyBriefingConfig, DailyBriefingRunner, main

__all__ = ["DailyBriefingConfig", "DailyBriefingRunner", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
