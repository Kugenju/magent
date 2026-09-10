"""VulnTell 应用配置（阶段 1，Task 1.1，阶段 5 扩展）。

不可变（frozen）配置对象，统一 CLI 与未来 API 的输入。CLI 参数转换为配置只做
解析与校验，不执行任何副作用；fixture 路径不依赖当前工作目录。

约束：
- 不保存 API key 明文或原始漏洞文本；
- 未知来源、空 run id、非法 checkpoint 组合应尽早报错；
- 所有路径使用 ``pathlib.Path``；
- live 模式需要显式开启，且只能使用已注册的来源；
- API key 只从环境变量注入，禁止进入序列化/trace/异常消息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AbstractSet, FrozenSet, Optional, Sequence
from urllib.parse import urlparse

_KNOWN_SOURCES: FrozenSet[str] = frozenset({"nvd", "cisa_kev", "cnvd", "osv", "github_advisory", "euvd", "msrc", "redhat", "ubuntu", "debian", "jvn", "certcc", "cisco", "fortinet", "paloalto", "exploitdb"})
# CNVD 官方 API 暂不可用，仅支持人工 fixture 模式
_KNOWN_SOURCES_FIXTURE_ONLY: FrozenSet[str] = frozenset()
_LIVE_ENDPOINTS: dict[str, str] = {
    "nvd": "https://services.nvd.nist.gov/rest/json/cves/2.0",
    "cisa_kev": "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    "osv": "https://osv.dev/list",
    "github_advisory": "https://api.github.com/advisories",
    "euvd": "https://euvd.enisa.europa.eu/api",
    "msrc": "https://api.msrc.microsoft.com/cvrf/v3.0/updates",
    "redhat": "https://access.redhat.com/hydra/rest/securitydata/cve.json",
    "ubuntu": "https://ubuntu.com/security/cves.json",
    "debian": "https://security-tracker.debian.org/tracker/data/json",
    "jvn": "https://jvndb.jvn.jp/myjvnxmlfeed",
    "certcc": "https://www.kb.cert.org/vuls/api/vulnnotes",
    "cisco": "https://tools.cisco.com/security/center/servicesxml",
    "fortinet": "https://www.fortinet.com/fortiguard/psirt",
    "paloalto": "https://security.paloaltonetworks.com/api/v1/advisories",
    "exploitdb": "https://www.exploit-db.com/api",
}

# 来源可用性状态
SOURCE_AVAILABILITY: dict[str, str] = {
    "nvd": "available",
    "cisa_kev": "available",
    "cnvd": "manual_required",  # 官方 API 不可用
    "osv": "available",
    "github_advisory": "available",
    "euvd": "available",
    "msrc": "available",
    "redhat": "available",
    "ubuntu": "available",
    "debian": "available",
    "jvn": "available",
    "certcc": "manual_required",  # 需要 API 密钥
    "cisco": "manual_required",  # 需要特殊认证
    "fortinet": "manual_required",  # 需要特殊认证
    "paloalto": "manual_required",  # 需要特殊认证
    "exploitdb": "manual_required",  # 需要特殊认证
}


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
    # Live 模式配置
    live: bool = False
    mode: Optional[str] = None  # fixture/live；未指定时由 live 推导
    source: Optional[str] = None  # nvd, cisa_kev, cnvd
    window_days: int = 30  # 默认回溯天数
    endpoint: Optional[str] = None
    endpoint_allowlist: tuple[str, ...] = tuple(_LIVE_ENDPOINTS.values())
    timeout_seconds: float = 30.0
    api_key: Optional[str] = None  # 从环境变量注入，不序列化
    endpoint: Optional[str] = None
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", self.mode or ("live" if self.live else "fixture"))
        if self.mode not in {"fixture", "live"}:
            raise ValueError("mode 必须是 fixture 或 live")
        if self.mode == "live" and not self.live:
            object.__setattr__(self, "live", True)
        if self.window_days <= 0:
            raise ValueError("window_days 必须为正数")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须为正数")
        if not self.run_id:
            raise ValueError("run_id 不能为空")
        unknown = {s for s in self.faulty_sources if s not in _KNOWN_SOURCES}
        if unknown:
            raise ValueError(f"未知来源（不在 {sorted(_KNOWN_SOURCES)}）：{sorted(unknown)}")
        if self.checkpoint == ":memory:" and self.resume:
            raise ValueError("resume 不能与 :memory: checkpoint 同时使用（无持久化可恢复）")
        # Live 模式校验
        if self.live:
            if not self.source:
                raise ValueError("live 模式需要指定 --source")
            all_sources = _KNOWN_SOURCES | _KNOWN_SOURCES_FIXTURE_ONLY
            if self.source not in all_sources:
                raise ValueError(f"未知来源：{self.source}，可选：{sorted(all_sources)}")
            if self.source in _KNOWN_SOURCES_FIXTURE_ONLY and self.source != "cnvd":
                raise ValueError(f"来源 {self.source} 仅支持 fixture 模式")
            if self.endpoint is not None:
                allowed = _LIVE_ENDPOINTS.get(self.source)
                if allowed is None or urlparse(self.endpoint).netloc != urlparse(allowed).netloc:
                    raise ValueError("live endpoint 不在 allowlist 中")
            ep = self.endpoint or _LIVE_ENDPOINTS.get(self.source)
            if not ep:
                raise ValueError(f"来源 {self.source} 未配置 endpoint")
            if not any(ep == allowed or ep.startswith(allowed.rstrip("/") + "/") for allowed in self.endpoint_allowlist):
                raise ValueError("endpoint 不在 allowlist 中")

    @property
    def fixture_dir(self) -> Path:
        """fixture 路径固定（apps.vulntell.fixtures），不依赖当前工作目录。"""
        from apps.vulntell import FIXTURE_DIR

        return FIXTURE_DIR

    @property
    def is_live_mode(self) -> bool:
        """是否为 live 模式。"""
        return self.live and self.source is not None

    @property
    def window_start(self) -> datetime:
        """同步窗口起始时间（含）。"""
        return datetime.now(timezone.utc) - timedelta(days=self.window_days)

    @property
    def window_end(self) -> datetime:
        """同步窗口结束时间（不含）。"""
        return datetime.now(timezone.utc)

    def get_live_endpoint(self) -> Optional[str]:
        """获取 live 模式的 API endpoint。"""
        if not self.is_live_mode:
            return None
        return self.endpoint or _LIVE_ENDPOINTS.get(self.source)

    def get_api_key(self) -> Optional[str]:
        """获取 API key（仅从环境变量）。"""
        if not self.is_live_mode:
            return None
        import os
        env_key_map = {
            "nvd": "NVD_API_KEY",
            "cisa_kev": None,  # CISA KEV 不需要 API key
            "osv": None,  # OSV 不需要 API key
            "github_advisory": "GITHUB_TOKEN",
            "euvd": None,  # EUVD 不需要 API key
        }
        env_var = env_key_map.get(self.source)
        if env_var:
            return os.environ.get(env_var)
        return None

    def get_github_token(self) -> Optional[str]:
        """获取 GitHub token（仅从环境变量）。"""
        import os
        return os.environ.get("GITHUB_TOKEN")

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
        live: bool = False,
        source: Optional[str] = None,
        window_days: int = 30,
        mode: Optional[str] = None,
        endpoint: Optional[str] = None,
        endpoint_allowlist: Optional[Sequence[str]] = None,
        timeout_seconds: float = 30.0,
    ) -> "VulnTellConfig":
        """从 CLI 参数构建配置（仅解析与校验，无副作用）。"""
        import os
        api_key = None
        if live and source:
            env_key_map = {"nvd": "NVD_API_KEY"}
            env_var = env_key_map.get(source)
            if env_var:
                api_key = os.environ.get(env_var)
        return cls(
            db=db,
            checkpoint=checkpoint,
            run_id=run_id,
            no_llm=no_llm,
            json_output=json_output,
            faulty_sources=frozenset(faulty or ()),
            trace_prefix=trace,
            resume=resume,
            live=live,
            source=source,
            window_days=window_days,
            mode=mode,
            endpoint=endpoint,
            endpoint_allowlist=tuple(endpoint_allowlist or _LIVE_ENDPOINTS.values()),
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )
