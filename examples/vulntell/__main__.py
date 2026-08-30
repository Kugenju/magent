"""VulnTell 旧入口兼容转发（阶段 1，Task 1.4）。

阶段 1 结束后，旧目录的业务模块仍作为迁移过渡依赖；但所有运行都通过
``apps.vulntell`` 入口进入，旧入口只负责转发，避免存在第二份编排逻辑。

退出码语义与新入口一致：成功 0，运行失败 1，KeyboardInterrupt 130。
"""

from __future__ import annotations

import sys

from apps.vulntell.__main__ import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
