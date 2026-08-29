"""来源适配器（阶段 7）。

``SourceAdapter`` 是统一协议，默认只使用离线 ``FixtureSourceAdapter``。真实
HTTP 适配器通过 ``HttpSourceAdapter`` 的隔离接口声明，但默认不联网、需要凭据，
由后续阶段在明确开关下启用。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .loading import load_fixture
from .models import RawSourceRecord


@runtime_checkable
class SourceAdapter(Protocol):
    source: str

    async def fetch(
        self, dataset_id: str, dataset_version: str, observed_at
    ) -> list[RawSourceRecord]: ...


class FixtureSourceAdapter:
    """从本地 JSON fixture 加载来源原始记录，确定性、离线、无网络。"""

    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source

    async def fetch(
        self, dataset_id: str, dataset_version: str, observed_at
    ) -> list[RawSourceRecord]:
        return load_fixture(
            self.path,
            observed_at=observed_at,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )


class HttpSourceAdapter:
    """真实网络适配器的隔离接口（默认不实现，避免误联网）。

    启用真实采集时必须显式传入凭据与端点，并遵守阶段 4 的超时/可重试/限流策略。
     fixture 模式下 CLI 不应构造本类。
    """

    def __init__(self, source: str, *, endpoint: str, api_key: str | None = None) -> None:
        self.source = source
        self.endpoint = endpoint
        self.api_key = api_key

    async def fetch(
        self, dataset_id: str, dataset_version: str, observed_at
    ) -> list[RawSourceRecord]:
        raise NotImplementedError(
            "HttpSourceAdapter is disabled by default; use FixtureSourceAdapter offline"
        )


class FaultySourceAdapter:
    """用于测试部分失败语义的故障注入适配器（默认不联网）。"""

    def __init__(self, source: str, *, error: str = "injected source failure") -> None:
        self.source = source
        self._error = error

    async def fetch(
        self, dataset_id: str, dataset_version: str, observed_at
    ) -> list[RawSourceRecord]:
        raise RuntimeError(self._error)
