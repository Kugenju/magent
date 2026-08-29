"""阶段 7 — 业务持久化幂等测试。"""

from __future__ import annotations

import datetime as dt
import pathlib

from examples.vulntell.db import VulnTellStore
from examples.vulntell.dedupe import deduplicate
from examples.vulntell.loading import load_dataset_meta, load_fixture
from examples.vulntell.metrics import compute_metrics
from examples.vulntell.models import EvaluationRun
from examples.vulntell.normalize import normalize_record

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples" / "vulntell" / "fixtures"
_OBSERVED = dt.datetime(2023, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc)


def _state():
    meta = load_dataset_meta(_FIXTURE_DIR / "dataset_meta.json")
    observations = []
    for f in ("nvd_sample.json", "cnvd_sample.json"):
        for raw in load_fixture(_FIXTURE_DIR / f, observed_at=_OBSERVED):
            obs, _ = normalize_record(raw)
            observations.append(obs)
    canonical, pending = deduplicate(observations)
    quality = [qi for o in observations for qi in o.quality_issues]
    m = compute_metrics(observations, canonical, pending, quality, meta, {"nvd": "ok", "cnvd": "ok"})
    return meta, observations, canonical, pending, quality, m


def test_idempotent_upsert_does_not_increase_counts():
    store = VulnTellStore(":memory:")
    store.init_schema()
    meta, observations, canonical, pending, quality, m = _state()
    raws = [r for f in ("nvd_sample.json", "cnvd_sample.json") for r in load_fixture(_FIXTURE_DIR / f, observed_at=_OBSERVED)]

    for r in raws:
        store.upsert_raw(r)
    for o in observations:
        store.upsert_observation(o)
    for c in canonical:
        store.upsert_canonical(c)
    store.insert_quality_issues(quality)
    store.upsert_metric(m)

    n_obs = store.count_observations()
    n_can = store.count_canonical()
    n_raw = store.count_raw()
    assert n_obs == 7 and n_can == 5 and n_raw == 7

    # 重复运行：唯一键保证数量不增加
    for o in observations:
        store.upsert_observation(o)
    for c in canonical:
        store.upsert_canonical(c)
    store.upsert_metric(m)
    assert store.count_observations() == n_obs
    assert store.count_canonical() == n_can
    store.close()


def test_metric_snapshot_unique_key():
    store = VulnTellStore(":memory:")
    store.init_schema()
    meta, observations, canonical, pending, quality, m = _state()
    store.upsert_metric(m)
    store.upsert_metric(m)
    # 仅一行（同一 dataset/version/window/metric_version）
    cur = store._conn.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0]
    assert cur == 1
    store.close()


def test_run_record_persisted():
    store = VulnTellStore(":memory:")
    store.init_schema()
    meta, _, _, _, _, _ = _state()
    run = EvaluationRun(
        run_id="run-x",
        dataset_id=meta.dataset_id,
        dataset_version=meta.dataset_version,
        window_start=meta.window_start,
        window_end=meta.window_end,
        started_at=_OBSERVED,
        status="success",
        framework_version=meta.framework_version,
    )
    store.upsert_run(run)
    row = store._conn.execute("SELECT status FROM evaluation_runs WHERE run_id='run-x'").fetchone()
    assert row["status"] == "success"
    store.close()
