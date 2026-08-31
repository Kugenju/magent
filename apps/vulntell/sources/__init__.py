"""VulnTell 数据源包（阶段 3/4/5/6/7/8）。

阶段 3 仅暴露 legacy 兼容层；阶段 4 引入正式的协议、分页适配器和错误分类。
阶段 5 引入真实 HTTP 适配器（NVD、CISA KEV、CNVD）和 live adapter 工厂。
阶段 6 引入 OSV、GitHub Advisory、EUVD 适配器。
阶段 7 引入 Microsoft MSRC、Red Hat、Ubuntu、Debian、JVN 适配器。
阶段 8 引入 CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB 适配器。
"""

from __future__ import annotations

from apps.vulntell.sources.certcc import CERTCCAdapter, CERTCCConfig
from apps.vulntell.sources.cisco import CiscoAdapter, CiscoConfig
from apps.vulntell.sources.cnvd import CNVDAdapter, CNVDConfig
from apps.vulntell.sources.cnvd_manual import CNVDManualConfig, CNVDManualFileSource
from apps.vulntell.sources.cisa_kev import CISAKEVAdapter, CISAKEVConfig
from apps.vulntell.sources.debian import DebianAdapter, DebianConfig
from apps.vulntell.sources.errors import (
    SourceError,
    SourceErrorKind,
    classify_exception,
    classify_http_status,
)
from apps.vulntell.sources.euvd import EUVDAdapter, EUVDConfig
from apps.vulntell.sources.exploitdb import ExploitDBAdapter, ExploitDBConfig
from apps.vulntell.sources.fixtures import (
    FaultyPagedSource,
    PagedFixtureConfig,
    PagedFixtureSource,
)
from apps.vulntell.sources.fortinet import FortinetAdapter, FortinetConfig
from apps.vulntell.sources.github_advisory import GitHubAdvisoryAdapter, GitHubAdvisoryConfig
from apps.vulntell.sources.jvn import JVNAdapter, JVNConfig
from apps.vulntell.sources.legacy import (
    FaultySourceAdapter,
    FixtureSourceAdapter,
    HttpSourceAdapter,
    SourceAdapter,
)
from apps.vulntell.sources.live_adapter import create_live_adapter, get_source_display_name
from apps.vulntell.sources.msrc import MSRCAdapter, MSRCConfig
from apps.vulntell.sources.nvd import NVDAdapter, NVDConfig
from apps.vulntell.sources.osv import OSVAdapter, OSVConfig
from apps.vulntell.sources.paloalto import PaloAltoAdapter, PaloAltoConfig
from apps.vulntell.sources.protocol import (
    SourcePage,
    SourceRecord,
    SourceRequest,
)
from apps.vulntell.sources.redhat import RedHatAdapter, RedHatConfig
from apps.vulntell.sources.ubuntu import UbuntuAdapter, UbuntuConfig

__all__ = [
    # 阶段 3 legacy 兼容
    "SourceAdapter",
    "FixtureSourceAdapter",
    "HttpSourceAdapter",
    "FaultySourceAdapter",
    # 阶段 4 协议
    "SourceRequest",
    "SourcePage",
    "SourceRecord",
    # 阶段 4 分页适配器
    "PagedFixtureSource",
    "PagedFixtureConfig",
    "FaultyPagedSource",
    # 阶段 4 错误分类
    "SourceError",
    "SourceErrorKind",
    "classify_http_status",
    "classify_exception",
    # 阶段 5 NVD adapter
    "NVDAdapter",
    "NVDConfig",
    # 阶段 5 CISA KEV adapter
    "CISAKEVAdapter",
    "CISAKEVConfig",
    # 阶段 5 CNVD adapter
    "CNVDAdapter",
    "CNVDConfig",
    "CNVDManualConfig",
    "CNVDManualFileSource",
    # 阶段 5 live adapter 工厂
    "create_live_adapter",
    "get_source_display_name",
    # 阶段 6 OSV adapter
    "OSVAdapter",
    "OSVConfig",
    # 阶段 6 GitHub Advisory adapter
    "GitHubAdvisoryAdapter",
    "GitHubAdvisoryConfig",
    # 阶段 6 EUVD adapter
    "EUVDAdapter",
    "EUVDConfig",
    # 阶段 7 Microsoft MSRC adapter
    "MSRCAdapter",
    "MSRCConfig",
    # 阶段 7 Red Hat adapter
    "RedHatAdapter",
    "RedHatConfig",
    # 阶段 7 Ubuntu adapter
    "UbuntuAdapter",
    "UbuntuConfig",
    # 阶段 7 Debian adapter
    "DebianAdapter",
    "DebianConfig",
    # 阶段 7 JVN adapter
    "JVNAdapter",
    "JVNConfig",
    # 阶段 8 CERT/CC adapter
    "CERTCCAdapter",
    "CERTCCConfig",
    # 阶段 8 Cisco adapter
    "CiscoAdapter",
    "CiscoConfig",
    # 阶段 8 Fortinet adapter
    "FortinetAdapter",
    "FortinetConfig",
    # 阶段 8 Palo Alto adapter
    "PaloAltoAdapter",
    "PaloAltoConfig",
    # 阶段 8 Exploit-DB adapter
    "ExploitDBAdapter",
    "ExploitDBConfig",
]
