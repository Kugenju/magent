# Changelog

All notable changes to the `magent` project are documented here. The project is in the `0.x` phase:
additive fields and non-breaking behavior may be added; any breaking change is recorded explicitly and
bumps the minor version. The offline-first, no-API-key, no-network default is a stability commitment.

## [0.1.0] — release candidate (phase 9)

### Release hardening (phase 9)
- Documentation consistency across README / API / DESIGN / ROADMAP / PHASE docs.
- `docs/architecture/COMPARISON.md`: design comparison with LangGraph / AutoGen / CrewAI (not ranked).
- `LICENSE` (MIT) and `THIRD_PARTY_NOTICES.md` (dependencies, fixtures, safe-use boundaries).
- GitHub Actions CI: Python 3.11/3.12/3.13, full pytest, `mypy src/magent`, offline smoke tests,
  generated-artifact guard.
- `pyproject.toml`: description/version/license finalized; `mypy` added to `.[dev]` extras.
- Release security/packaging gates (`tests/unit/test_phase9_release.py`): secret scan, no top-level
  network imports, VulnTell trace excludes raw payload, reference comparison never ranked.
- `examples/quickstart.py`: shortest Agent → State → Result → report example.

### Already shipped (phases 1–8)
- Phase 1: typed `Agent` / `State` / `AgentResult` / `Runtime`; sequential executor.
- Phase 2: Graph builder, validation, conditional routing, sequential graph executor.
- Phase 3: concurrent DAG, fan-out/fan-in, reducers, in-process `EventBus`.
- Phase 4: node timeout, bounded retry, caller cancellation, error classification.
- Phase 5: opt-in SQLite checkpoint, crash recovery, idempotent side effects, stable execution key.
- Phase 6: tool protocol (schema-validated, allowlist, timeout, size-limit), pluggable LLM provider
  (`FakeProvider` + optional lazy OpenAI adapter), composable middleware.
- Phase 7: `examples/vulntell` offline vertical example (multi-source collection → normalize → quality
  alerts → dedupe → persist → concurrent recoverable graph → aggregate metrics → report).
- Phase 8: read-only observability (`Trace`/`Span`/`RunSummary` + redaction), offline `benchmarks/`
  runner (determinism / isolation / parallel reliability / checkpoint recovery), VulnTell source-quality
  evaluation, and a reference-framework comparison recorder that never ranks.

## Compatibility policy (0.x)
- New optional fields on public models are additive and safe.
- A breaking change to a public API or execution semantic requires a minor-version bump and a CHANGELOG note.
- The default offline behavior (no network, no API key, no real LLM) is preserved across releases.
