"""共享 HTTP transport 配置。

代理通过 ``VULNTELL_PROXY`` 显式设置，例如
``http://127.0.0.1:7890``；未设置时沿用系统 HTTP(S)_PROXY 环境变量。
"""
from __future__ import annotations
import os

def proxy_url() -> str | None:
    return (os.environ.get("VULNTELL_PROXY") or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY") or os.environ.get("ALL_PROXY"))

def client_kwargs() -> dict:
    proxy = proxy_url()
    return {"proxy": proxy} if proxy else {}
