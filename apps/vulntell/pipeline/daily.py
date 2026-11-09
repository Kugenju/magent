"""VulnTell 每日简报工作流（阶段 10 桥接：多源采集 -> 确定性评估 -> 前端展示）。

一次 ``DailyBriefingRunner.run()`` 完成整条多 agent 协作链：

1. **并行采集**（任意来源集合的 Graph 扇出，失败来源降级不阻塞）——默认
   ``cisa_kev``（直连 REST，免 key）+ ``osv_mcp``（MCP 协议路径，自持
   FastMCP server，`osv_get_payload` 样本检索）；
2. **归一化/去重/持久化**——与常规 VulnTell 流程同一 `ToolRegistry` +
   `SideEffectSink` 幂等管线；
3. **确定性评估**——`compute_metrics` 全套指标 + dashboard 侧 `compute_source_metrics`
   每来源快照（样本不足记 ``insufficient_data``，不做无依据排名）；
4. **双路径对照**（live）——OSV 同端点直连 GET 与 MCP `osv_get_payload`
   各读一次，比较 canonical hash 与归一化字段一致性；
5. **输出**——`dashboard.html`（静态、零依赖、双击可看）+ `report.md` /
   `report.json`（+ live 的 `dual_path.json`）。

调度（每日自动）：Windows 用任务计划程序包同一条命令（见
``scripts/daily_briefing.ps1`` 与 ``docs/vulntell/daily_briefing.md``）。

run_id 日期锚定（``daily-YYYYMMDD``）：同日重跑幂等（SQLite upsert + 幂等
副作用管线），产物目录按日期归档。

依赖注入：测试可整体替换 ``adapters`` / ``http_fetch`` / ``mcp_transport_factory``，
默认离线路径不联网、不产出 ``dual_path.json``（live 才有）。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, cast

from magent import ExecutionReport, GraphExecutor
from magent.checkpoint import SideEffectSink, SqliteCheckpointStore
from magent.checkpoint.models import canonical_json, checksum_of

from apps.vulntell.config import VulnTellConfig  # noqa: F401  (exposed for CLI parity)
from apps.vulntell.domain.models import DatasetMeta, RawSourceRecord
from apps.vulntell.pipeline.graph import build_daily_vulntell_graph
from apps.vulntell.pipeline.jobs import VulnTellRunResult
from apps.vulntell.pipeline.state import VulnTellState
from apps.vulntell.sources.cisa_kev import CISAKEVAdapter, CISAKEVConfig
from apps.vulntell.sources.mcp_adapter import McpSourceAdapter
from apps.vulntell.sources.mcp_bridge import DualPathProbe, HttpFetch, TransportFactory
from apps.vulntell.storage.legacy import VulnTellStore

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SERVER = _REPO_ROOT / "tools" / "mcp_example_server.py"

# 双路径对照的默认样本 IDs（公开已知、OSV 已索引的高关注样本；其余历史
# CVE 若不在 OSV 索引中会作为"同形失败"对照行保留，同样是证据）。
DEFAULT_OSV_SAMPLE_IDS: tuple[str, ...] = (
    "CVE-2024-3094",
    "CVE-2021-44228",
    "CVE-2020-1472",
)


@dataclass
class DailyBriefingConfig:
    """每日简报的一次运行配置（不可变输入，CLI 在此收敛）。"""

    run_date: Optional[dt.date] = None  # None -> 今天（UTC） YYYY-MM-DD 归档
    window_days: int = 7
    sources: tuple[str, ...] = ("cisa_kev", "osv_mcp")
    osv_sample_ids: tuple[str, ...] = DEFAULT_OSV_SAMPLE_IDS[:2]
    mcp_tool_name: str = "osv_get_payload"
    mcp_server_script: Path = _DEFAULT_SERVER
    call_timeout: float = 60.0
    db: str = ""  # "" -> out_dir / f"{run_id}.sqlite3"
    checkpoint: str = ":memory:"
    out_dir: Optional[Path] = None  # None -> repo runs/<run_id>
    max_kev_records: Optional[int] = None  # 受控批次上限（演示/烟测可调小）
    skip_dual_path: bool = False

    def __post_init__(self) -> None:
        if self.window_days <= 0:
            raise ValueError("window_days 必须为正数")
        unknown = set(self.sources) - {"cisa_kev", "osv_mcp"}
        if unknown:
            raise ValueError(f"暂不支持的日报来源：{sorted(unknown)}")
        if "osv_mcp" in self.sources and not self.osv_sample_ids:
            raise ValueError("osv_mcp 来源需要至少一个样本 CVE ID")


@dataclass
class DailyBriefingResult:
    """一次运行的结构化产物。"""

    run_id: str
    out_dir: Path
    outputs: dict[str, Path]
    pipeline: VulnTellRunResult
    dual_path: Optional[dict] = None
    source_summaries: dict[str, dict] = field(default_factory=dict)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _probe_default_http_fetch() -> HttpFetch:
    """REST 直连读取（live）：httpx 懒导入 + VulnTell 代理约定。"""

    async def fetch(url: str) -> dict:
        import httpx  # 懒导入：离线路径永不触碰 `net` extra

        from apps.vulntell.sources.http import client_kwargs

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0), **client_kwargs()
        ) as client:
            resp = await client.get(
                url,
                headers={"Accept": "application/json", "User-Agent": "vulntell-daily/1.0"},
            )
            resp.raise_for_status()
            return resp.json()

    return fetch


class _DailyKEVAdapter:
    """KEV feed 适配：复用既有 `CISAKEVAdapter.fetch_page`（受控批次+窗口内筛）。

    内层 adapter 的 ``SourceRecord.payload`` 已是 VulnTell 归一化键
    （cve_id/title/description/published_at/modified_at/source_added_at/...，
    见 cisa_kev.py），此处只负责分页拉全并包成 ``RawSourceRecord``。
    """

    def __init__(
        self,
        *,
        window_start: dt.datetime,
        max_records: Optional[int] = None,
        transport: Optional[Any] = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._inner = CISAKEVAdapter(
            CISAKEVConfig(timeout_seconds=timeout_seconds, max_records=max_records),
        )
        if transport is not None:
            self._inner._transport = transport  # noqa: SLF001 - 测试注入点
        self._window_start = window_start
        self.last_summary: dict = {"requested": None, "fetched": 0, "failed": {}}

    async def fetch(
        self, dataset_id: str, dataset_version: str, observed_at: dt.datetime
    ) -> list[RawSourceRecord]:
        from apps.vulntell.sources.errors import SourceError
        from apps.vulntell.sources.protocol import SourceRequest

        end = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=dt.timezone.utc)
        request = SourceRequest(
            source="cisa_kev",
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            window_start=self._window_start,
            window_end=end,
            page_size=200,
        )
        out: list[RawSourceRecord] = []
        cursor: Optional[str] = None
        seen_cursors: set[str] = set()
        while True:
            page = await self._inner.fetch_page(request, cursor)
            if isinstance(page, SourceError):
                raise RuntimeError(f"cisa_kev: {page.message}")
            for rec in page.records:
                payload = dict(rec.payload)
                payload.setdefault("aliases", [payload.get("cve_id")] if payload.get("cve_id") else [])
                out.append(
                    RawSourceRecord(
                        source="cisa_kev",
                        record_id=rec.source_record_id,
                        observed_at=page.observed_at,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        payload=payload,
                        payload_hash=checksum_of(canonical_json(payload)),
                    )
                )
            self.last_summary["fetched"] = len(out)
            # 终止条件：无更多 | 无游标 | 空页 | 游标停滞（防御性，页游标永不回退）
            if not page.has_more or not page.next_cursor or not page.records:
                break
            if page.next_cursor in seen_cursors:
                break
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        return out

    async def aclose(self) -> None:  # 与 MCP 适配器同接口（连接无状态）
        return None


class DailyBriefingRunner:
    """每日简报编排（一次构造，一次 ``run()``；离线可测、live 可调度）。"""

    def __init__(
        self,
        config: DailyBriefingConfig,
        *,
        provider=None,
        adapters: Optional[dict[str, Any]] = None,
        http_fetch: Optional[HttpFetch] = None,
        mcp_transport_factory: Optional[TransportFactory] = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._adapters = adapters
        self._http_fetch = http_fetch
        self._mcp_factory = mcp_transport_factory

    # -- meta / adapters ------------------------------------------------

    def _build_meta(self, sources: list[str]) -> DatasetMeta:
        import magent

        now = _utc_now()
        if self._config.run_date is not None:
            window_end = dt.datetime.combine(
                self._config.run_date, dt.time(0, 0), tzinfo=dt.timezone.utc
            )
        else:
            window_end = now
        window_start = window_end - dt.timedelta(days=self._config.window_days)
        return DatasetMeta(
            dataset_id="vulntell-daily",
            dataset_version=f"daily-{window_end:%Y%m%d}",
            window_start=window_start,
            window_end=window_end,
            framework_version=getattr(magent, "__version__", "0.x"),
            license="public-data",
            sources=sources,
        )

    def _default_mcp_factory(self, errlog_path: Path) -> TransportFactory:
        """真实 stdio transport factory（懒加载 SDK；进程 stderr 落 errlog）。"""

        def factory() -> Any:
            from magent.mcp.stdio import stdio_transport

            errlog = open(errlog_path, "a", encoding="utf-8", errors="replace")
            forwarded = {
                key: os.environ[key]
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
                if os.environ.get(key)
            }
            return stdio_transport(
                sys.executable,
                args=(str(self._config.mcp_server_script),),
                env=forwarded,
                errlog=errlog,
            )

        return factory

    def _build_adapters(self, meta: DatasetMeta, out_dir: Path) -> dict[str, Any]:
        if self._adapters is not None:
            return dict(self._adapters)
        adapters: dict[str, Any] = {}
        if "cisa_kev" in self._config.sources:
            adapters["cisa_kev"] = _DailyKEVAdapter(
                window_start=meta.window_start,
                max_records=self._config.max_kev_records,
            )
        if "osv_mcp" in self._config.sources and self._config.osv_sample_ids:
            adapters["osv_mcp"] = McpSourceAdapter(
                source="osv_mcp",
                tool_name=self._config.mcp_tool_name,
                vuln_ids=self._config.osv_sample_ids,
                transport_factory=self._mcp_factory
                or self._default_mcp_factory(out_dir / "mcp_server_stderr.log"),
                window_start=meta.window_start,
                call_timeout=self._config.call_timeout,
            )
        if not adapters:
            raise ValueError("daily 配置没有产生任何数据源 adapter")
        return adapters

    # -- run ------------------------------------------------------------

    async def run(self) -> DailyBriefingResult:
        config = self._config
        anchor = config.run_date or _utc_now().date()
        run_id = f"daily-{anchor:%Y%m%d}"
        out_dir = config.out_dir or (_REPO_ROOT / "runs" / run_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        meta = self._build_meta(sources=sorted(config.sources))

        adapters = self._build_adapters(meta, out_dir)
        store = VulnTellStore(config.db or str(out_dir / f"{run_id}.sqlite3"))
        checkpoint_store = SqliteCheckpointStore(config.checkpoint)
        sink = SideEffectSink(checkpoint_store, run_id=run_id, node_id="persist", node_version="1")

        graph = build_daily_vulntell_graph(meta, store, sink, self._provider, adapters=adapters)
        executor = GraphExecutor(
            graph, run_id=run_id, max_concurrency=4, checkpoint_store=checkpoint_store
        )
        try:
            final_state, execution_report = await executor.run(VulnTellState(meta=meta))
        finally:
            await checkpoint_store.close()
            for adapter in adapters.values():
                aclose = getattr(adapter, "aclose", None)
                if aclose is not None:
                    await aclose()

        # GraphExecutor 的通用 API 返回 BaseModel；日报图的状态和报告类型
        # 已由构图入口固定，这里显式收窄类型，避免业务层丢失类型检查。
        final_state = cast(VulnTellState, final_state)
        execution_report = cast(ExecutionReport, execution_report)

        from apps.vulntell.domain.models import Report
        from apps.vulntell.reporting.exporters import to_json as export_json
        from apps.vulntell.reporting.exporters import to_markdown

        report = Report(**final_state.report) if final_state.report else None
        outputs: dict[str, Path] = {}
        if report is not None:
            outputs["report.md"] = out_dir / "report.md"
            outputs["report.md"].write_text(to_markdown(report), encoding="utf-8")
            outputs["report.json"] = out_dir / "report.json"
            outputs["report.json"].write_text(export_json(report), encoding="utf-8")

        dual_path: Optional[dict] = None
        if "osv_mcp" in adapters and config.osv_sample_ids and not config.skip_dual_path:
            probe = DualPathProbe(
                cve_ids=config.osv_sample_ids,
                mcp_transport_factory=self._mcp_factory
                or self._default_mcp_factory(out_dir / "mcp_probe_stderr.log"),
                http_fetch=self._http_fetch or _probe_default_http_fetch(),
                tool_name=config.mcp_tool_name,
                call_timeout=config.call_timeout,
            )
            try:
                dual_path = await probe.run()
            except Exception as exc:  # noqa: BLE001 - 探针失败不阻塞简报，记录形态
                dual_path = {"summary": {"error": f"{type(exc).__name__}: {exc}"}, "rows": []}
            outputs["dual_path.json"] = out_dir / "dual_path.json"
            outputs["dual_path.json"].write_bytes(
                json.dumps(dual_path, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            )

        source_summaries = {
            name: dict(getattr(adapter, "last_summary", {}))
            for name, adapter in adapters.items()
        }

        # dashboard（含报告为 None 的降级形态：仍展示执行时间线与来源摘要）
        from apps.vulntell.reporting.dashboard import write_dashboard

        outputs["dashboard.html"] = out_dir / "dashboard.html"
        write_dashboard(
            outputs["dashboard.html"],
            run_id=run_id,
            meta=meta,
            report=report,
            final_state=final_state,
            execution_report=execution_report,
            dual_path=dual_path,
            source_summaries=source_summaries,
        )

        pipeline = VulnTellRunResult(
            final_state=final_state, execution_report=execution_report, report=report
        )
        return DailyBriefingResult(
            run_id=run_id,
            out_dir=out_dir,
            outputs=outputs,
            pipeline=pipeline,
            dual_path=dual_path,
            source_summaries=source_summaries,
        )


# ----------------------------------------------------------------------
# CLI: python -m apps.vulntell.daily
# ----------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.vulntell.daily",
        description="VulnTell 每日简报：多源采集 -> 确定性评估 -> 静态前端展示",
    )
    parser.add_argument("--date", default=None, help="锚定日期 YYYY-MM-DD（默认今天 UTC；影响 run_id 与窗口末端）")
    parser.add_argument("--window-days", type=int, default=7, help="回溯窗口天数（默认 7）")
    parser.add_argument(
        "--sources", default="cisa_kev,osv_mcp",
        help="逗号分隔来源集合（当前支持 cisa_kev, osv_mcp）",
    )
    parser.add_argument(
        "--osv-ids", default=",".join(DEFAULT_OSV_SAMPLE_IDS[:2]),
        help="osv_mcp 样本 CVE ID（逗号分隔）",
    )
    parser.add_argument("--out", default=None, help="输出目录（默认 runs/<run_id>）")
    parser.add_argument("--db", default="", help="SQLite 路径（默认 out/<run_id>.sqlite3）")
    parser.add_argument("--checkpoint", default=":memory:")
    parser.add_argument("--max-kev-records", type=int, default=None, help="KEV 受控批次上限")
    parser.add_argument("--skip-dual-path", action="store_true", help="不跑双路径对照")
    parser.add_argument("--timeout", type=float, default=60.0, help="MCP/HTTP 单调用超时秒")
    args = parser.parse_args(argv)

    run_date: Optional[dt.date] = None
    if args.date:
        run_date = dt.date.fromisoformat(args.date)
    config = DailyBriefingConfig(
        run_date=run_date,
        window_days=args.window_days,
        sources=tuple(s.strip() for s in args.sources.split(",") if s.strip()),
        osv_sample_ids=tuple(s.strip() for s in args.osv_ids.split(",") if s.strip()),
        out_dir=Path(args.out) if args.out else None,
        db=args.db,
        checkpoint=args.checkpoint,
        max_kev_records=args.max_kev_records,
        skip_dual_path=args.skip_dual_path,
        call_timeout=args.timeout,
    )
    started = time.perf_counter()
    result = asyncio.run(DailyBriefingRunner(config).run())
    elapsed = time.perf_counter() - started

    pipeline = result.pipeline
    print(f"[daily] run_id={result.run_id} out={result.out_dir}")
    for name, path in sorted(result.outputs.items()):
        print(f"[daily]   {name} -> {path}")
    if pipeline.report is not None:
        print(f"[daily] source_status={pipeline.report.source_status}")
        print(
            f"[daily] canonical={pipeline.report.canonical_count} "
            f"pending={pipeline.report.pending_count} "
            f"quality={pipeline.report.quality_issue_count} "
            f"insufficient_data={pipeline.report.insufficient_data}"
        )
    if result.dual_path is not None:
        summary = result.dual_path.get("summary", {})
        print(
            f"[daily] dual_path: sample={summary.get('sample_size')} "
            f"hash_equal={summary.get('hash_equal')} "
            f"same_shape_failures={summary.get('same_shape_failures')}"
        )
    print(f"[daily] elapsed={elapsed:.1f}s")
    failed = pipeline.execution_report.failed_agent if pipeline.execution_report else None
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
