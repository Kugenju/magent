# Third-party notices, data sources and attribution

This project is released under the MIT License (see `LICENSE`). The sections below record dependency
licenses, reference-project attribution, dataset/fixture provenance, and safe-use boundaries.

## Dependencies

- **pydantic** (>=2.5): MIT licensed. https://github.com/pydantic/pydantic — used for all typed state
  and result models. Ships with the runtime; no network or API key required.
- **pytest** / **pytest-asyncio** / **mypy**: development-only dependencies (optional `.[dev]` extra).
  Not required to run the framework or examples.

## Optional LLM adapter

- The OpenAI adapter (if present) is **lazily imported** and is never required for offline execution.
  VulnTell uses the deterministic `FakeProvider` for non-binding textual explanations. No API key or
  network access is needed for any default command.

## Reference frameworks (comparison only)

The following projects are referenced **only** for design comparison in `docs/architecture/COMPARISON.md` and recorded
as `not_comparable` in `benchmarks/reference_comparison.py`. No source code, binaries, or assets from these
projects are copied or distributed:

- LangGraph — https://github.com/langchain-ai/langgraph (license: MIT)
- AutoGen — https://github.com/microsoft/autogen (license: MIT/Apache-2.0, per upstream)
- CrewAI — https://github.com/crewAIInc/crewAI (license: per upstream)

Exact versions/commits must be pinned at verification time via `pip show` or a locked Git commit; the
comparison does not constitute an endorsement or performance ranking.

## Dataset / fixture provenance

- `examples/vulntell/fixtures/*` are **synthetic, desensitized demonstration data**. They are not real
  vulnerability-intelligence records and must not be interpreted as current threat statistics.
- Report outputs produced from these fixtures are illustrative only and are explicitly marked
  `insufficient_data` / sample-limited where applicable.

## Safe-use boundaries

- The project does **not** perform active vulnerability scanning, PoC execution, exploitation, or external
  command execution.
- External vulnerability text is never written to logs, `Trace`, `Checkpoint`, or reports (enforced by the
  observability redaction contract and tests).
- No keys, tokens, or private data are present in the repository; `benchmarks/out/`, databases, caches and
  `.env` are git-ignored.
