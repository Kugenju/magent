"""阶段 8 重复运行统计（Task 3）。

至少保存 n、均值、中位数、p95、最小值和最大值；先断言结果一致再统计（性能更快但结果错误
的运行无效）。
"""

from __future__ import annotations

import math
from typing import Sequence


def summarize(values: Sequence[float]) -> dict:
    """返回 n / mean / median / p95 / min / max 聚合统计。"""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return {"n": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    mean = sum(s) / n
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    idx = min(n - 1, max(0, int(math.ceil(0.95 * n)) - 1))
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "p95": s[idx],
        "min": s[0],
        "max": s[-1],
    }
