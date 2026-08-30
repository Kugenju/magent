"""VulnTell 应用生命周期（阶段 1 Task 1.2，阶段 3 重写导向 apps.pipeline）。

``VulnTellApplication`` 是新旧入口唯一进入业务实现的位置：它把配置适配到
``apps.vulntell.pipeline.jobs.VulnTellJobRunner``（集中的任务服务），并打包为
结构化结果。

本服务不重新实现 Graph 调度、重试、Checkpoint 或状态合并——这些全部委托给
``magent`` 与 ``apps.vulntell.pipeline`` 现有实现。阶段 3 不再依赖
``examples.vulntell.run``，业务编排的唯一实现位于 apps 内。
"""

from __future__ import annotations

from apps.vulntell.pipeline.jobs import VulnTellJobRunner, VulnTellRunResult

from .config import VulnTellConfig


class VulnTellApplication:
    """组装依赖并执行一次任务的应用服务。"""

    def __init__(self, config: VulnTellConfig, *, provider=None) -> None:
        self._config = config
        self._provider = provider

    async def run(self) -> VulnTellRunResult:
        runner = VulnTellJobRunner(self._config, provider=self._provider)
        if self._config.resume:
            return await runner.resume(self._config.run_id)
        return await runner.run()

    async def resume(self, run_id: str) -> VulnTellRunResult:
        runner = VulnTellJobRunner(self._config, provider=self._provider)
        return await runner.resume(run_id)
