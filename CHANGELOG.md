# Changelog

All notable changes to the `magent` project are documented here. The project is in the `0.x` phase:
additive fields and non-breaking behavior may be added; any breaking change is recorded explicitly and
bumps the minor version. Offline-by-default (optional extras only) remains a stability commitment;
networking is a documented, explicitly-configured first-class capability — see
`docs/architecture/NETWORK_POLICY.md`.

## [Unreleased] — phase 10 (MCP client adapter, P10.2 real stdio verified; first real downstream: VulnTell daily briefing)

### Added
- **VulnTell daily briefing workflow** (first real downstream use of the phase-10 MCP
  channel): `python -m apps.vulntell.daily` runs a multi-source parallel collection graph
  (`pipeline/graph.py:build_daily_vulntell_graph`, N-source fan-out reusing the frozen
  agent/node conventions) over keyless sources — CISA KEV direct REST + a local MCP server
  (`tools/mcp_example_server.py:new osv_get_payload` raw-JSON tool) — then the unchanged
  normalize/dedupe/persist/evaluate pipeline, per-source deterministic metrics
  (`compute_source_metrics`), an OSV **dual-path consistency probe**
  (`apps/vulntell/sources/mcp_bridge.py`: same-endpoint direct GET vs MCP tool call,
  canonical-hash + field agreement), and a static single-file dashboard
  (`apps/vulntell/reporting/dashboard.py`: agent timeline, source status, per-source
  metric cards, quality-issue aggregation, dual-path table, canonical preview; no
  external URLs, embedded `application/json` data frame with `<`-escaping). Outputs:
  `dashboard.html` / `report.md` / `report.json` / `dual_path.json` under a date-anchored,
  re-runnable `runs/daily-YYYYMMDD/`. Scheduling: `scripts/daily_briefing.ps1` +
  documented schtasks command; guide in `docs/DAILY_WORKFLOW.md`.
- `apps/vulntell/sources/mcp_adapter.py`: `McpSourceAdapter` — data-plane use of the
  `magent.mcp` transport seam as a VulnTell source (CollectAgent-compatible `fetch`),
  OSV-→payload mapping, per-ID failure isolation (all-fail degrades the source), window
  filter, FastMCP `{"result": ...}` envelope tolerance, offline-tested against
  `magent.mcp.fake`.
- `docs/vulntell/daily_briefing.md`: operational guide (stages, defaults, scheduler, network
  boundaries, phase-10 relationship).
- `docs/architecture/NETWORK_POLICY.md`: layered network policy replacing the strict
  "whole-project offline" stance. The default install/test/CI baseline stays offline and
  deterministic; live traffic becomes a documented, explicitly-configured capability
  (opt-in switches, endpoint allowlists, env-var keys) building on the existing VulnTell
  live-mode precedents.
- `docs/phases/PHASE10_MCP_CLIENT.md`: phase-10 plan + implementation record for the MCP
  client adapter (external MCP servers' tools registered into the phase-6 `ToolRegistry`
  policy pipeline).
- `src/magent/mcp/` (P10.1 skeleton, offline): `McpTransport` seam + `McpCallOutcome`,
  `McpServerConfig`/`McpToolDescriptor`/`McpToolEntry`/`McpToolsetSnapshot` (toolset
  fingerprint), JSON-Schema-subset → pydantic converter (`absent`/`typed`/`untyped`
  fallbacks), `McpToolProxy` adapter (side-effect hints → `SideEffectSink` funnel,
  per-call timeout hard wall, EventBus event side channel), two-pass `McpToolLoader`
  (explicit allowlists required by default, collision refusal, fail-close on abort),
  classified `McpToolError` taxonomy (retryable kinds also satisfy `RetryableError`
  for `ReliabilityPolicy`), and the offline doubles (`FakeMcpServer` /
  `InMemoryMcpTransport` / `FakeTransportFactory`).
- `src/magent/mcp/stdio.py` (P10.2, real): `StdioMcpTransport` over the official MCP SDK —
  local server processes via `stdio_client`/`ClientSession` with an `AsyncExitStack`
  lifecycle (idempotent connect, rollback on partial connect, safe double-close), SDK
  types confined inside the module (lazy imports keep the core SDK-free), progress
  notifications forwarded into the proxy's sync hook, and every SDK exception normalized
  via `map_transport_exception` (TimeoutError→timeout; JSON-RPC codes → invalid/transient
  with `CONNECTION_CLOSED=-32000`→transient; OSError→transient; unknown→permanent).
- `src/magent/mcp/schema.py` hardening (driven by real-server verification): internal
  `$defs` + `#/` `$ref` resolution with a depth cap (pydantic-generated schemas always
  hide enums/nested models behind refs) and the strict optional pattern
  `anyOf: [X, null]` (= pydantic `Optional[X]`) now convert to typed models; true
  unions / allOf / oneOf / if / not still degrade to an explicit `untyped` mode.
- `tools/mcp_example_server.py` (new asset, stdio): real FastMCP server with read-only
  tools — `echo`, `profile_query` (real enum via `Service(str, Enum)`), `osv_lookup`
  (public OSV.dev read; in-server failures surface to clients as uniform `isError`
  results with kind `permanent`).
- `tests/live/test_mcp_stdio_smoke.py` (new): real-process stdio smoke through the full
  pipeline (spawn → initialize → list_tools → loader/allowlist → registry invoke → typed
  enum rejection against the real server schema → uniform server-failure shape → real
  OSV read). Opt-in only: `live` pytest marker + `MAGENT_RUN_LIVE=1` env gate; the
  default (offline) run skips them and never spawns processes or touches the network.
- `pyproject.toml`: new optional extras `mcp = ["mcp>=1.10,<2"]` (official MCP Python SDK) and
  `net = ["httpx>=0.27,<1"]`. The core runtime dependency set (`pydantic`) is unchanged.
  P10.2: registered the `live` pytest marker for opt-in real-process/network tests.

### Fixed
- `apps/vulntell/config.py`: removed duplicated `endpoint` / `timeout_seconds` field
  declarations (silent last-wins override in the frozen dataclass).
- `apps/vulntell/sources/cisa_kev.py`: `max_records` sampling truncated `end_idx`, which
  made later pages slice `vulnerabilities[start:end]` with `start > end` (always empty)
  and kept `has_more = end_idx < total` permanently true — a paged consumer could loop
  forever. Semantics corrected ("sampling truncation stops pagination after the capped
  first batch"); the pre-existing unit test (`record_count == 10` on page 1) still passes.
  Uncovered by the phase-10 daily live smoke; the daily wrapper additionally guards
  against empty/stalled cursors.
- `apps/vulntell/sources/mcp_adapter.py` payload mapping avoids the `severity` list key
  (`normalize_record` passes it into the CVSS sub-model where `severity` is a string).

### Changed
- README / docs navigation: offline-first wording updated to "offline by default + explicit
  network capability" with links to the network policy.

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
- Phase 7: `apps/vulntell` offline vertical example (multi-source collection → normalize → quality
  alerts → dedupe → persist → concurrent recoverable graph → aggregate metrics → report);
  `examples/vulntell` remains as a compatibility entry point.
- Phase 8: read-only observability (`Trace`/`Span`/`RunSummary` + redaction), offline `benchmarks/`
  runner (determinism / isolation / parallel reliability / checkpoint recovery), VulnTell source-quality
  evaluation, and a reference-framework comparison recorder that never ranks.

## Compatibility policy (0.x)
- New optional fields on public models are additive and safe.
- A breaking change to a public API or execution semantic requires a minor-version bump and a CHANGELOG note.
- The default offline behavior (no network, no API key, no real LLM) is preserved across releases.
