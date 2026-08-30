"""VulnTell 阶段 3 迁移 contract 测试（PHASE3_PLAN.md Task 3.7）。

验证运行时编排已从 examples.vulntell 迁移到 apps.vulntell.pipeline，且：
- apps 侧不再依赖 examples.vulntell.{run,state,agents,graph}（仅允许 legacy 兼容层引用 db/sources）；
- State schema / reducers 与冻结基线一致；
- 新 Graph 产出的报告逐字段等价于阶段 0 冻结基线（含部分失败语义）；
- full / resume 结果等价且幂等；
- 应用服务统一关闭资源；
- 新 Pipeline 不发起任何网络连接；
- 旧 examples 入口仅作转发，与 apps 入口等价。
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from unittest import mock

from helpers import normalize_report_for_compare, run_cli_entrypoint

_BASELINE_DIR = pathlib.Path(__file__).resolve().parent / "baselines"


def _load_baseline(name: str) -> dict:
    return json.loads((_BASELINE_DIR / name).read_text(encoding="utf-8"))


# ---- Task 3.3：apps 侧不依赖旧运行时模块 ----


def test_pipeline_source_does_not_import_examples_runtime() -> None:
    """apps.vulntell.pipeline 与 application 不得反向 import examples.vulntell.{run,state,agents,graph}。"""
    root = pathlib.Path(__file__).resolve().parents[3] / "apps" / "vulntell"
    forbidden = [
        "examples.vulntell.run",
        "examples.vulntell.state",
        "examples.vulntell.agents",
        "examples.vulntell.graph",
    ]
    scanned = list(root.glob("*.py")) + list((root / "pipeline").glob("*.py"))
    for f in scanned:
        # 仅检查 import 语句，避免 docstring 中的示例文本误报
        for line in f.read_text(encoding="utf-8").splitlines():
            if "import" not in line:
                continue
            for fb in forbidden:
                assert fb not in line, f"{f} 不应 import {fb}（阶段 3 已迁移）"


def test_examples_runtime_modules_are_shims() -> None:
    """examples.vulntell.{run,state,agents,graph} 必须是转发到 apps 的薄壳，无第二份实现。"""
    import apps.vulntell.pipeline.agents as pa
    import apps.vulntell.pipeline.graph as pg
    import apps.vulntell.pipeline.jobs as pj
    import apps.vulntell.pipeline.state as ps
    import examples.vulntell.agents as ea
    import examples.vulntell.graph as eg
    import examples.vulntell.run as er
    import examples.vulntell.state as es

    assert er.run_vulntell is pj.run_vulntell
    assert es.VulnTellState is ps.VulnTellState
    assert ea.CollectAgent is pa.CollectAgent
    assert eg.build_vulntell_graph is pg.build_vulntell_graph


# ---- Task 3.1 / 3.4：State schema 与报告等价 ----


def test_state_schema_and_reducers_are_stable() -> None:
    from apps.vulntell.pipeline.state import VulnTellState

    assert set(VulnTellState.model_fields) == {
        "meta",
        "raw",
        "observations_by_source",
        "canonical",
        "pending",
        "quality_issues",
        "source_status",
        "failed_sources",
        "metrics",
        "report",
    }
    assert set(VulnTellState.reducers) == {
        "raw",
        "observations_by_source",
        "source_status",
        "failed_sources",
    }


def test_graph_report_matches_baseline() -> None:
    from apps.vulntell.pipeline.jobs import run_vulntell

    result = asyncio.run(run_vulntell(no_llm=True, run_id="p3-base"))
    assert normalize_report_for_compare(result.report.model_dump()) == _load_baseline(
        "baseline_no_llm.json"
    )


def test_partial_failure_matches_baseline() -> None:
    from apps.vulntell.pipeline.jobs import run_vulntell

    result = asyncio.run(
        run_vulntell(no_llm=True, faulty_sources={"cnvd"}, run_id="p3-partial")
    )
    rep = result.report.model_dump()
    assert rep["source_status"]["cnvd"] == "failed"
    assert rep["source_status"]["nvd"] == "ok"
    assert rep["canonical_count"] == 4
    assert normalize_report_for_compare(rep) == _load_baseline("baseline_faulty_cnvd.json")


# ---- Task 3.5：恢复等价与幂等 ----


def test_resume_is_idempotent() -> None:
    import tempfile

    from apps.vulntell.pipeline.jobs import run_vulntell
    from examples.vulntell.db import VulnTellStore

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        db_path = str(tmp_path / "run.db")
        ckpt_path = str(tmp_path / "ckpt.db")
        run_id = "p3-resume"

        full = asyncio.run(
            run_vulntell(
                db=db_path, checkpoint=ckpt_path, run_id=run_id, no_llm=True, resume=False
            )
        )
        resumed = asyncio.run(
            run_vulntell(
                db=db_path, checkpoint=ckpt_path, run_id=run_id, no_llm=True, resume=True
            )
        )
        rerun = asyncio.run(
            run_vulntell(
                db=db_path, checkpoint=ckpt_path, run_id=run_id, no_llm=True, resume=True
            )
        )

        assert normalize_report_for_compare(
            full.report.model_dump()
        ) == normalize_report_for_compare(resumed.report.model_dump())
        assert normalize_report_for_compare(
            resumed.report.model_dump()
        ) == normalize_report_for_compare(rerun.report.model_dump())

        store = VulnTellStore(db_path)
        obs_full = store.count_observations()
        store.close()
        store = VulnTellStore(db_path)
        obs_rerun = store.count_observations()
        store.close()
        assert obs_rerun == obs_full
        assert obs_full > 0


# ---- Task 3.6：应用服务统一关闭资源 / 无网络副作用 ----


def test_application_closes_resources() -> None:
    import shutil
    import tempfile

    from apps.vulntell.application import VulnTellApplication
    from apps.vulntell.config import VulnTellConfig
    from apps.vulntell.storage.legacy import VulnTellStore

    tmp = tempfile.mkdtemp()
    try:
        tmp_path = pathlib.Path(tmp)
        db_path = str(tmp_path / "app.db")
        ckpt_path = str(tmp_path / "ckpt.db")
        cfg = VulnTellConfig(db=db_path, checkpoint=ckpt_path, run_id="p3-app", no_llm=True)
        app = VulnTellApplication(cfg)

        closed = []
        orig_close = VulnTellStore.close

        def _spy_close(self):
            orig_close(self)
            closed.append(True)

        with mock.patch.object(VulnTellStore, "close", _spy_close):
            result = asyncio.run(app.run())
        assert result.report is not None
        assert closed, "应用服务必须调用 store.close() 释放资源"

        store = VulnTellStore(db_path)
        assert store.count_observations() > 0
        store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_new_pipeline_has_no_network_side_effect() -> None:
    from apps.vulntell.pipeline.jobs import run_vulntell

    # 先建事件循环（其 socketpair 会调用 connect），再在运行期屏蔽网络
    loop = asyncio.new_event_loop()
    try:
        with mock.patch(
            "socket.socket.connect", side_effect=OSError("network blocked")
        ), mock.patch(
            "socket.create_connection", side_effect=OSError("network blocked")
        ):
            result = loop.run_until_complete(
                run_vulntell(no_llm=True, run_id="p3-offline")
            )
    finally:
        loop.close()
    assert result.report is not None
    assert result.report.canonical_count == 5


# ---- Task 3.2：旧入口仅作转发，与 apps 等价 ----


def test_old_entrypoint_remains_compatible() -> None:
    from apps.vulntell.pipeline.graph import build_vulntell_graph as new_graph
    from apps.vulntell.pipeline.state import VulnTellState as new_state
    from examples.vulntell.graph import build_vulntell_graph as old_graph
    from examples.vulntell.run import run_vulntell as old_run
    from examples.vulntell.state import VulnTellState as old_state

    assert old_graph is new_graph
    assert old_state is new_state

    result = asyncio.run(old_run(no_llm=True, run_id="p3-compat"))
    assert normalize_report_for_compare(result.report.model_dump()) == _load_baseline(
        "baseline_no_llm.json"
    )


def test_apps_and_examples_entrypoints_equivalent() -> None:
    rc1, rep1 = run_cli_entrypoint("apps.vulntell", ["--no-llm"])
    rc2, rep2 = run_cli_entrypoint("examples.vulntell", ["--no-llm"])
    assert rc1 == 0 and rc2 == 0
    assert normalize_report_for_compare(rep1) == normalize_report_for_compare(rep2)
