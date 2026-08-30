"""VulnTell 业务 Agent（阶段 3 从 examples.vulntell.agents 迁移，语义不变）。

各 Agent 只通过 ``AgentResult.updates`` 提议状态变更，不修改框架持有的 State。
采集分支在来源失败时降级（记录 ``source_status=failed``），从而保留其他来源结果
并实现“部分失败”语义；它不向上抛异常，以免触发框架 fail_fast 丢弃整条流程。

依赖通过构造函数注入：``SourceAdapter``、repository/store、``ToolRegistry`` /
``SideEffectSink``、LLM Provider、运行配置。Agent 不在内部读取环境变量、系统时间
或创建全局连接。
"""

from __future__ import annotations

from typing import Any

from magent import AgentResult, BaseAgent, ExecutionStatus
from magent.llm import ChatMessage, LLMRequest

from apps.vulntell.domain.dedupe import deduplicate
from apps.vulntell.domain.metrics import compute_metrics
from apps.vulntell.domain.models import (
    CanonicalVulnerability,
    DatasetMeta,
    EvaluationRun,
    MetricSnapshot,
    QualityIssue,
    RawSourceRecord,
    SourceObservation,
    utc,
)
from apps.vulntell.domain.normalize import normalize_record
from apps.vulntell.reporting.report import build_report
from apps.vulntell.sources.legacy import SourceAdapter
from apps.vulntell.storage.legacy import VulnTellStore


def _load_meta(state) -> DatasetMeta:
    return state.meta


class CollectAgent(BaseAgent):
    """采集单一来源；失败降级而非抛异常。"""

    def __init__(self, source: str, adapter: SourceAdapter) -> None:
        super().__init__(f"collect_{source}")
        self._source = source
        self._adapter = adapter

    async def run(self, state, runtime) -> AgentResult:
        try:
            recs = await self._adapter.fetch(
                state.meta.dataset_id, state.meta.dataset_version, state.meta.window_end
            )
            return AgentResult(
                updates={
                    "raw": {self._source: [r.model_dump() for r in recs]},
                    "source_status": {self._source: "ok"},
                }
            )
        except Exception as exc:  # noqa: BLE001 - 降级为部分失败
            return AgentResult(
                status=ExecutionStatus.SUCCESS,
                updates={
                    "raw": {self._source: []},
                    "source_status": {self._source: "failed"},
                    "failed_sources": [self._source],
                },
                message=f"collect {self._source} failed: {exc}",
            )


class NormalizeAgent(BaseAgent):
    """把某一来源的原始记录标准化为 SourceObservation。"""

    def __init__(self, source: str) -> None:
        super().__init__(f"normalize_{source}")
        self._source = source

    async def run(self, state, runtime) -> AgentResult:
        raws = [RawSourceRecord(**r) for r in state.raw.get(self._source, [])]
        obs_list = []
        for raw in raws:
            obs, _ = normalize_record(raw)
            obs_list.append(obs.model_dump())
        # 透传来源状态，使 join 能合并多分支的 source_status / failed_sources
        return AgentResult(
            updates={
                "observations_by_source": {self._source: obs_list},
                "source_status": state.source_status,
                "failed_sources": state.failed_sources,
            }
        )


class DedupeAgent(BaseAgent):
    """按 CVE 强匹配合并为 canonical，无 CVE 进入 pending。"""

    async def run(self, state, runtime) -> AgentResult:
        obs: list[SourceObservation] = []
        for lst in state.observations_by_source.values():
            for d in lst:
                obs.append(SourceObservation(**d))
        canonical, pending = deduplicate(obs)
        return AgentResult(
            updates={
                "canonical": [c.model_dump() for c in canonical],
                "pending": [p.model_dump() for p in pending],
            }
        )


class PersistAgent(BaseAgent):
    """将观察/漏洞写入业务库（通过阶段 6 的 side-effect 工具 + SideEffectSink 幂等）。"""

    def __init__(self, registry, sink) -> None:
        super().__init__("persist")
        self._registry = registry
        self._sink = sink

    async def run(self, state, runtime) -> AgentResult:
        from magent import ToolContext

        observations = [
            SourceObservation(**d)
            for lst in state.observations_by_source.values()
            for d in lst
        ]
        canonical = [CanonicalVulnerability(**d) for d in state.canonical]
        pending = [SourceObservation(**d) for d in state.pending]
        ctx = ToolContext(run_id=runtime.run_id, node_id=self.name, side_effect_sink=self._sink)
        res = await self._registry.invoke(
            "persist_batch",
            {
                "observations": [o.model_dump() for o in observations],
                "canonical": [c.model_dump() for c in canonical],
                "pending": [p.model_dump() for p in pending],
            },
            ctx,
        )
        if not res.ok:
            return AgentResult(status=ExecutionStatus.FAILED, message=str(res.error))
        return AgentResult(updates={}, message="persisted")


class EvaluateAgent(BaseAgent):
    """计算确定性指标快照。"""

    async def run(self, state, runtime) -> AgentResult:
        observations = [
            SourceObservation(**d)
            for lst in state.observations_by_source.values()
            for d in lst
        ]
        canonical = [CanonicalVulnerability(**d) for d in state.canonical]
        pending = [SourceObservation(**d) for d in state.pending]
        quality = [qi for o in observations for qi in o.quality_issues]
        m = compute_metrics(observations, canonical, pending, quality, state.meta, state.source_status)
        return AgentResult(
            updates={
                "metrics": m.model_dump(),
                "quality_issues": [qi.model_dump() for qi in quality],
            }
        )


class ReportAgent(BaseAgent):
    """生成可追溯报告；可选 LLM 解释不修改确定性结果。"""

    def __init__(self, provider=None) -> None:
        super().__init__("report")
        self._provider = provider

    async def run(self, state, runtime) -> AgentResult:
        observations = [
            SourceObservation(**d)
            for lst in state.observations_by_source.values()
            for d in lst
        ]
        canonical = [CanonicalVulnerability(**d) for d in state.canonical]
        pending = [SourceObservation(**d) for d in state.pending]
        quality = [QualityIssue(**d) for d in state.quality_issues]
        m = MetricSnapshot(**state.metrics)

        llm_explanation = None
        llm_failed = False
        if self._provider is not None:
            try:
                resp = await self._provider.complete(
                    LLMRequest(
                        messages=[
                            ChatMessage(
                                role="system",
                                content="用中文解释下列漏洞指标（不要修改任何数值）。",
                            ),
                            ChatMessage(role="user", content=str(m.metrics)),
                        ]
                    ).with_tools([])
                )
                llm_explanation = resp.message.content
            except Exception:  # noqa: BLE001 - LLM 失败不影响结构化报告
                llm_failed = True

        rep = build_report(
            state.meta,
            state.source_status,
            canonical,
            pending,
            quality,
            m,
            llm_explanation=llm_explanation,
            llm_failed=llm_failed,
        )
        return AgentResult(updates={"report": rep.model_dump()})
