"""VulnTell 任务生命周期（阶段 3 从 examples.vulntell.run 迁移，阶段 5 扩展）。

VulnTellJobRunner 封装一次评测任务的完整生命周期：加载数据集元数据、组装 store /
checkpoint / sink / provider / adapters、构建并运行 GraphExecutor、转换为结构化结果、
关闭资源。full 与 resume 共用同一 runner；资源关闭统一使用 try/finally。

``run_vulntell`` 为兼容函数，保留 examples.vulntell.run.run_vulntell 的调用形态，
供既有 contract 测试与示例脚本直接调用。

阶段 5 扩展：支持 live 模式，可选择性启用真实 HTTP adapter。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

from magent import ExecutionReport, GraphExecutor
from magent.checkpoint import SideEffectSink, SqliteCheckpointStore
from magent.llm import FakeProvider

from apps.vulntell.config import VulnTellConfig
from apps.vulntell.domain.models import Report
from apps.vulntell.domain.schemas import load_dataset_meta
from apps.vulntell.pipeline.graph import build_vulntell_graph
from apps.vulntell.pipeline.state import VulnTellState
from apps.vulntell.sources.live_adapter import create_live_adapter
from apps.vulntell.storage.legacy import VulnTellStore

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures"


@dataclass
class VulnTellRunResult:
    final_state: VulnTellState
    execution_report: ExecutionReport
    report: Optional[Report]


class VulnTellJobRunner:
    """一次 VulnTell 任务的执行器（不再依赖 examples.vulntell.run）。"""

    def __init__(
        self,
        config: VulnTellConfig,
        *,
        provider=None,
        fixture_dir: Optional[pathlib.Path] = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._fixture_dir = fixture_dir or config.fixture_dir

    async def run(self) -> VulnTellRunResult:
        return await self._execute(resume=False)

    async def resume(self, run_id: str) -> VulnTellRunResult:
        return await self._execute(resume=True, run_id=run_id)

    async def _execute(self, *, resume: bool, run_id: Optional[str] = None) -> VulnTellRunResult:
        run_id = run_id or self._config.run_id
        meta = load_dataset_meta(self._fixture_dir / "dataset_meta.json")
        store = VulnTellStore(self._config.db)
        checkpoint_store = SqliteCheckpointStore(self._config.checkpoint)
        sink = SideEffectSink(checkpoint_store, run_id=run_id, node_id="persist", node_version="1")
        provider = self._provider if self._provider is not None else (FakeProvider() if not self._config.no_llm else None)

        # 创建 live adapters
        live_adapters = {}
        if self._config.is_live_mode:
            live_adapter = create_live_adapter(self._config)
            if live_adapter:
                live_adapters[self._config.source] = live_adapter

        graph = build_vulntell_graph(
            meta,
            store,
            sink,
            provider,
            fixture_dir=self._fixture_dir,
            faulty_sources=set(self._config.faulty_sources),
            live_adapters=live_adapters,
        )
        state = VulnTellState(meta=meta)
        executor = GraphExecutor(
            graph, run_id=run_id, max_concurrency=4, checkpoint_store=checkpoint_store
        )
        try:
            if resume:
                final_state, execution_report = await executor.resume(run_id, state)
            else:
                final_state, execution_report = await executor.run(state)
        finally:
            store.close()
            await checkpoint_store.close()
        report = Report(**final_state.report) if final_state.report else None
        return VulnTellRunResult(
            final_state=final_state, execution_report=execution_report, report=report
        )


async def run_vulntell(
    *,
    db: str = ":memory:",
    checkpoint: str = ":memory:",
    run_id: str = "vulntell-demo-run",
    no_llm: bool = False,
    faulty_sources=None,
    fixture_dir: Optional[pathlib.Path] = None,
    resume: bool = False,
    provider=None,
    live: bool = False,
    source: Optional[str] = None,
    window_days: int = 30,
) -> VulnTellRunResult:
    """兼容便捷函数：构造配置并运行（默认 fixture 为 apps 内置）。"""
    config = VulnTellConfig(
        db=db,
        checkpoint=checkpoint,
        run_id=run_id,
        no_llm=no_llm,
        faulty_sources=frozenset(faulty_sources or set()),
        resume=resume,
        live=live,
        source=source,
        window_days=window_days,
    )
    runner = VulnTellJobRunner(config, provider=provider, fixture_dir=fixture_dir)
    if resume:
        return await runner.resume(run_id)
    return await runner.run()
