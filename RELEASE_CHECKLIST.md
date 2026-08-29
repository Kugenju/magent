# Release checklist (phase 9)

Use this checklist before creating a GitHub release / tag. Each item must be verified; do not ship while
any blocking item is open.

## Build & install
- [ ] Clean virtual environment install `pip install -e ".[dev]"` succeeds (no network/API key needed).
- [ ] `import magent` and `importlib.metadata.version("magent")` return `0.1.0`.
- [ ] `examples/` and `benchmarks/` run from source checkout (intentionally not in the wheel).

## Tests & types
- [ ] Full suite `python -m pytest -q` passes (baseline: 250 passed).
- [ ] `mypy src/magent` passes.
- [ ] `python -m pytest tests/unit/test_phase9_release.py -q` passes (release gates).

## CI
- [ ] GitHub Actions green on Python 3.11, 3.12, 3.13.
- [ ] Offline smoke tests (core / checkpoint / tools-LLM / VulnTell / benchmark CLI) succeed in CI.
- [ ] No tracked generated artifacts (`*.db`, `*.jsonl`, `benchmarks/out/*`).

## Docs & links
- [ ] README / API / DESIGN / ROADMAP / PHASE1–9 status consistent.
- [ ] `docs/COMPARISON.md`, `docs/BENCHMARKS.md` present and linked.
- [ ] All README commands run successfully in a clean checkout.

## License & compliance
- [ ] `LICENSE` (MIT) and `THIRD_PARTY_NOTICES.md` present.
- [ ] Secret scan clean (no keys / tokens / `.env` / databases in repo).
- [ ] VulnTell fixtures are synthetic/desensitized; reports not presented as real intel.
- [ ] External vulnerability text absent from logs / Trace / Checkpoint / reports.

## Scope boundaries (published honestly)
- [ ] README/notes state what is **not** delivered: distributed execution, dynamic planning, production
      Web dashboard, cross-framework ranking, PyPI formal release (unless separately accepted).
- [ ] Benchmark results labeled sample-limited and not a performance guarantee.

## Release notes
- [ ] Release notes list implemented capabilities, non-goals, offline limits, and the not-comparable
      reference boundary.
- [ ] Working tree clean; no sensitive files; no generated outputs committed.

## Tagging
- [ ] Maintainer confirms the candidate checklist, then creates the `v0.1.0` tag / GitHub release.

> PyPI formal publishing and a production Web dashboard are **out of scope** for this release and must be
> accepted in separate, standalone reviews.
