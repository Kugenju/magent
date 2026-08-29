"""阶段 9 — 发布门禁：许可证、打包元数据、秘密扫描、离线/不可比边界。"""

from __future__ import annotations

import asyncio
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tracked_text_files(exts=(".py", ".md", ".toml", ".txt", ".json", ".cfg", ".ini", ".yml", ".yaml")):
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except Exception:
        return []
    files = []
    for rel in out.splitlines():
        p = ROOT / rel
        if p.suffix in exts and p.exists():
            files.append(p)
    return files


def test_license_present():
    lic = ROOT / "LICENSE"
    assert lic.exists()
    assert "MIT License" in lic.read_text(encoding="utf-8")


def test_third_party_notices_present():
    notice = ROOT / "THIRD_PARTY_NOTICES.md"
    assert notice.exists()
    text = notice.read_text(encoding="utf-8")
    assert "pydantic" in text
    assert "fixture" in text.lower()


def test_pyproject_metadata():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    proj = data["project"]
    assert proj["version"] == "0.1.0"
    assert "mypy" in str(proj["optional-dependencies"].get("dev", []))
    desc = proj["description"]
    assert "phase 1 kernel" not in desc
    assert "phases 1-8" in desc or "phases 1–8" in desc


def test_gitignore_excludes_generated():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "benchmarks/out/" in gi
    assert "*.db" in gi
    assert "*.jsonl" in gi


SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r'(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*["\'][^\s"\']{16,}["\']'),
]


def test_no_secrets_in_repo():
    offenders = []
    for p in _tracked_text_files():
        if "tests/" in str(p) or "benchmarks/out" in str(p):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                offenders.append(str(p))
                break
    assert not offenders, f"possible secrets in: {offenders}"


NETWORK_IMPORT = re.compile(r"^\s*(import|from)\s+(requests|httpx|aiohttp)\b")


def test_no_top_level_network_imports():
    offenders = []
    for p in _tracked_text_files(exts=(".py",)):
        if "tests/" in str(p):
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if NETWORK_IMPORT.match(line):
                offenders.append(f"{p}:{line.strip()}")
    assert not offenders, f"network imports: {offenders}"


def test_vulntell_trace_excludes_raw_payload():
    from examples.vulntell.db import VulnTellStore
    from examples.vulntell.graph import build_vulntell_graph
    from examples.vulntell.loading import load_dataset_meta
    from examples.vulntell.state import VulnTellState
    from magent import GraphExecutor
    from magent.checkpoint import SideEffectSink, SqliteCheckpointStore
    from magent.checkpoint.models import state_schema_hash
    from magent.observability import build_observability

    meta = load_dataset_meta("examples/vulntell/fixtures/dataset_meta.json")
    store = VulnTellStore(":memory:")
    store.init_schema()
    sink = SideEffectSink(SqliteCheckpointStore(":memory:"), run_id="rel", node_id="persist", node_version="1")
    graph = build_vulntell_graph(meta, store, sink, None, fixture_dir=pathlib.Path("examples/vulntell/fixtures"))
    fstate = VulnTellState(meta=meta)
    _final, report = asyncio.run(GraphExecutor(graph, run_id="rel", max_concurrency=4).run(fstate))
    store.close()
    schema = state_schema_hash(VulnTellState)
    t, spans, summary = build_observability(report, workflow_id="graph", workflow_version="1", state_schema_version=schema)
    blob = t.model_dump_json() + "".join(s.model_dump_json() for s in spans) + summary.model_dump_json()
    assert "raw_payload" not in blob


def test_reference_comparison_not_ranked():
    from benchmarks.reference_comparison import collect_reference_comparison, to_comparison_report

    recs = collect_reference_comparison()
    assert all(r.status == "not_comparable" for r in recs)
    assert to_comparison_report(recs)["ranking"] is None


def test_readme_offline_and_commands():
    text = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "offline" in text
    assert "python examples/quickstart.py" in text
    assert "python -m benchmarks.cli" in text


def test_ci_workflow_present():
    wf = ROOT / ".github" / "workflows" / "ci.yml"
    assert wf.exists()
    text = wf.read_text(encoding="utf-8")
    assert "pytest" in text and "mypy" in text
    for v in ("3.11", "3.12", "3.13"):
        assert v in text
