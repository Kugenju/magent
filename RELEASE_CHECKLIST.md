# Release checklist (phase 9)

Use this checklist before creating a GitHub release / tag. Each item must be verified; do not ship while
any blocking item is open.

## Build & install
- [x] Clean virtual environment install `pip install -e ".[dev]"` succeeds (no network/API key needed).
- [x] `import magent` and `importlib.metadata.version("magent")` return `0.1.0`.
- [x] `examples/` and `benchmarks/` run from source checkout (intentionally not in the wheel).

## Tests & types
- [x] Full suite `python -m pytest -q` passes (current: 260 passed).
- [x] `mypy src/magent` passes.
- [x] `python -m pytest tests/unit/test_phase9_release.py -q` passes (10 passed).

## CI
- [ ] GitHub Actions green on Python 3.11, 3.12, 3.13 (requires remote repository access).
- [ ] Offline smoke tests (core / checkpoint / tools-LLM / VulnTell / benchmark CLI) succeed in CI.
- [x] No tracked generated artifacts (`*.db`, `*.jsonl`, `benchmarks/out/*`).

## Docs & links
- [x] README / API / DESIGN / ROADMAP / PHASE1–9 status consistent.
- [x] `docs/architecture/COMPARISON.md`, `docs/evaluation/BENCHMARKS.md` present and linked.
- [x] All README commands run successfully in the local checkout.

## License & compliance
- [x] `LICENSE` (MIT) and `THIRD_PARTY_NOTICES.md` present.
- [x] Secret scan clean (no keys / tokens / `.env` / databases in repo).
- [x] VulnTell fixtures are synthetic/desensitized; reports not presented as real intel.
- [x] External vulnerability text absent from logs / Trace / Checkpoint / reports.

## Scope boundaries (published honestly)
- [x] README/notes state what is **not** delivered: distributed execution, dynamic planning, production
      Web dashboard, cross-framework ranking, PyPI formal release (unless separately accepted).
- [x] Benchmark results labeled sample-limited and not a performance guarantee.

## Release notes
- [x] Release notes list implemented capabilities, non-goals, offline limits, and the not-comparable
      reference boundary.
- [x] Working tree clean before this checklist update; no sensitive files; no generated outputs committed.

## Tagging
- [ ] Maintainer confirms the candidate checklist, then creates the `v0.1.0` tag / GitHub release.

> PyPI formal publishing and a production Web dashboard are **out of scope** for this release and must be
> accepted in separate, standalone reviews.
