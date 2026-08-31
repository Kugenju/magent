"""VulnTell Live 适配器工厂（阶段 5，Task 5C.1，阶段 6/7/8 扩展）。

根据配置创建对应的 live adapter，支持 NVD、CISA KEV、OSV、GitHub Advisory、EUVD、
Microsoft MSRC、Red Hat、Ubuntu、Debian、JVN。
CNVD、CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB 暂不支持 live 模式。

约束：
- 默认不联网，需要显式传入 transport
- API key 只从环境变量注入
- 不把完整 raw payload 写入 State/Trace/日志
"""

from __future__ import annotations

from typing import Optional

from apps.vulntell.config import SOURCE_AVAILABILITY, VulnTellConfig
from apps.vulntell.sources.cisa_kev import CISAKEVAdapter, CISAKEVConfig
from apps.vulntell.sources.debian import DebianAdapter, DebianConfig
from apps.vulntell.sources.euvd import EUVDAdapter, EUVDConfig
from apps.vulntell.sources.github_advisory import GitHubAdvisoryAdapter, GitHubAdvisoryConfig
from apps.vulntell.sources.jvn import JVNAdapter, JVNConfig
from apps.vulntell.sources.msrc import MSRCAdapter, MSRCConfig
from apps.vulntell.sources.nvd import NVDAdapter, NVDConfig
from apps.vulntell.sources.osv import OSVAdapter, OSVConfig
from apps.vulntell.sources.protocol import SourcePage, SourceRecord, SourceRequest
from apps.vulntell.sources.redhat import RedHatAdapter, RedHatConfig
from apps.vulntell.sources.ubuntu import UbuntuAdapter, UbuntuConfig


class LiveSourceAdapter:
    """Live 模式数据源 adapter 接口。"""

    async def fetch_page(
        self, request: SourceRequest, cursor: Optional[str] = None
    ) -> SourcePage:
        raise NotImplementedError

    async def fetch(self, dataset_id: str, dataset_version: str, observed_at):
        """兼容旧 CollectAgent 的批量接口，拉取所有分页并转换为 RawSourceRecord。"""
        from apps.vulntell.domain.models import RawSourceRecord
        from magent.checkpoint.models import canonical_json, checksum_of
        from datetime import timedelta
        from apps.vulntell.sources.protocol import SourceRequest
        req = SourceRequest(source=getattr(self, "source", "nvd"), dataset_id=dataset_id,
                            dataset_version=dataset_version, window_start=observed_at,
                            window_end=observed_at + timedelta(microseconds=1))
        out=[]; cursor=None
        while True:
            page = await self.fetch_page(req, cursor)
            if not hasattr(page, "records"):
                raise RuntimeError(getattr(page, "message", "source error"))
            for rec in page.records:
                out.append(RawSourceRecord(source=rec.metadata.get("source", req.source), record_id=rec.source_record_id,
                    observed_at=page.observed_at, dataset_id=dataset_id, dataset_version=dataset_version,
                    payload=rec.payload, payload_hash=checksum_of(canonical_json(rec.payload))))
            if not page.has_more: break
            cursor=page.next_cursor
        return out


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

    # 检查来源可用性
    availability = SOURCE_AVAILABILITY.get(config.source, "manual_required")
    if availability == "manual_required":
        raise ValueError(
            f"来源 '{config.source}' 暂不支持 live 模式。请使用人工 fixture 模式。"
        )

    if config.source == "nvd":
        nvd_config = NVDConfig(
            api_key=config.get_api_key(),
            endpoint=config.get_live_endpoint() or NVDConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = NVDAdapter(config=nvd_config, transport=transport)
        adapter.source = "nvd"
        return adapter

    elif config.source == "cisa_kev":
        cisa_config = CISAKEVConfig(
            endpoint=config.get_live_endpoint() or CISAKEVConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = CISAKEVAdapter(config=cisa_config, transport=transport)
        adapter.source = "cisa_kev"
        return adapter

    elif config.source == "osv":
        osv_config = OSVConfig(
            endpoint=config.get_live_endpoint() or OSVConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = OSVAdapter(config=osv_config, transport=transport)
        adapter.source = "osv"
        return adapter

    elif config.source == "github_advisory":
        github_config = GitHubAdvisoryConfig(
            endpoint=config.get_live_endpoint() or GitHubAdvisoryConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = GitHubAdvisoryAdapter(
            config=github_config,
            transport=transport,
            token=config.get_github_token(),
        )
        adapter.source = "github_advisory"
        return adapter

    elif config.source == "euvd":
        euvd_config = EUVDConfig(
            endpoint=config.get_live_endpoint() or EUVDConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = EUVDAdapter(config=euvd_config, transport=transport)
        adapter.source = "euvd"
        return adapter

    elif config.source == "msrc":
        msrc_config = MSRCConfig(
            endpoint=config.get_live_endpoint() or MSRCConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = MSRCAdapter(config=msrc_config, transport=transport)
        adapter.source = "msrc"
        return adapter

    elif config.source == "redhat":
        redhat_config = RedHatConfig(
            endpoint=config.get_live_endpoint() or RedHatConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = RedHatAdapter(config=redhat_config, transport=transport)
        adapter.source = "redhat"
        return adapter

    elif config.source == "ubuntu":
        ubuntu_config = UbuntuConfig(
            endpoint=config.get_live_endpoint() or UbuntuConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = UbuntuAdapter(config=ubuntu_config, transport=transport)
        adapter.source = "ubuntu"
        return adapter

    elif config.source == "debian":
        debian_config = DebianConfig(
            endpoint=config.get_live_endpoint() or DebianConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = DebianAdapter(config=debian_config, transport=transport)
        adapter.source = "debian"
        return adapter

    elif config.source == "jvn":
        jvn_config = JVNConfig(
            endpoint=config.get_live_endpoint() or JVNConfig.endpoint,
            timeout_seconds=config.timeout_seconds,
        )
        adapter = JVNAdapter(config=jvn_config, transport=transport)
        adapter.source = "jvn"
        return adapter

    return None


def get_source_display_name(source: str) -> str:
    """获取来源的显示名称。"""
    names = {
        "nvd": "NIST National Vulnerability Database",
        "cisa_kev": "CISA Known Exploited Vulnerabilities Catalog",
        "cnvd": "国家信息安全漏洞共享平台",
        "osv": "OSV.dev Open Source Vulnerabilities",
        "github_advisory": "GitHub Advisory Database",
        "euvd": "European Vulnerability Database",
        "msrc": "Microsoft Security Response Center",
        "redhat": "Red Hat Security Data",
        "ubuntu": "Ubuntu CVE Tracker",
        "debian": "Debian Security Tracker",
        "jvn": "Japan Vulnerability Notes",
        "certcc": "CERT/CC Vulnerability Notes",
        "cisco": "Cisco PSIRT",
        "fortinet": "Fortinet PSIRT",
        "paloalto": "Palo Alto Networks PSIRT",
        "exploitdb": "Exploit-DB",
    }
    return names.get(source, source)


def get_source_availability(source: str) -> str:
    """获取来源可用性状态。"""
    return SOURCE_AVAILABILITY.get(source, "manual_required")

