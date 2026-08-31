"""VulnTell Live 适配器工厂（阶段 5，Task 5C.1）。

根据配置创建对应的 live adapter，支持 NVD 和 CISA KEV。
CNVD 暂不支持 live 模式（官方 API 不可用）。

约束：
- 默认不联网，需要显式传入 transport
- API key 只从环境变量注入
- 不把完整 raw payload 写入 State/Trace/日志
"""

from __future__ import annotations

from typing import Optional

from apps.vulntell.config import VulnTellConfig
from apps.vulntell.sources.cisa_kev import CISAKEVAdapter, CISAKEVConfig
from apps.vulntell.sources.nvd import NVDAdapter, NVDConfig
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest


class LiveSourceAdapter:
    """Live 模式数据源 adapter 接口。"""

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage:
        raise NotImplementedError


def create_live_adapter(
    config: VulnTellConfig,
    transport: Optional[object] = None,
) -> Optional[LiveSourceAdapter]:
    """根据配置创建 live adapter。

    Args:
        config: VulnTell 配置
        transport: HTTP transport 函数（可选，用于测试）

    Returns:
        LiveSourceAdapter 或 None（如果配置不支持 live 模式）
    """
    if not config.is_live_mode:
        return None

    if config.source == "nvd":
        nvd_config = NVDConfig(
            api_key=config.get_api_key(),
        )
        return NVDAdapter(config=nvd_config, transport=transport)

    elif config.source == "cisa_kev":
        cisa_config = CISAKEVConfig()
        return CISAKEVAdapter(config=cisa_config, transport=transport)

    elif config.source == "cnvd":
        # CNVD 暂不支持 live 模式
        raise ValueError(
            "CNVD 暂不支持 live 模式。请使用人工 fixture 模式。"
        )

    return None


def get_source_display_name(source: str) -> str:
    """获取来源的显示名称。"""
    names = {
        "nvd": "NIST National Vulnerability Database",
        "cisa_kev": "CISA Known Exploited Vulnerabilities Catalog",
        "cnvd": "国家信息安全漏洞共享平台",
    }
    return names.get(source, source)
