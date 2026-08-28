"""Idempotency keys and side-effect guard (phase 5, §7).

A logical node execution — its retries and its recovery replay — must reuse the
same *execution key*, so an external side effect guarded by that key is only
performed once even if the agent runs more than once (at-least-once execution).
The framework cannot make an arbitrary external API exactly-once; it can only
guarantee that the same key is not double-applied when the caller uses the
idempotency layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .models import EffectRecord, canonical_json, checksum_of
from .store import CheckpointStore

_log = logging.getLogger("magent.checkpoint.idempotency")


def execution_key(
    run_id: str,
    node_id: str,
    node_version: str,
    input_state: dict[str, Any],
    logical_operation_name: str,
) -> str:
    """Stable, auditable key for one logical side effect.

    ``attempt`` is deliberately excluded so a retry or a recovery replay maps to
    the same key.
    """
    payload = {
        "run_id": run_id,
        "node_id": node_id,
        "node_version": node_version,
        "input_state": input_state,
        "op": logical_operation_name,
    }
    return "eff-" + checksum_of(canonical_json(payload))


class SideEffectSink:
    """Guards an external side effect behind its execution key.

    On replay the key is already recorded, so ``effect_fn`` is not invoked a
    second time and the previously recorded result is returned. ``write_count``
    counts actual invocations of ``effect_fn`` and is meant for tests/diagnostics.

    Concurrent calls for the same key are serialized by a per-key lock, so the
    effect is invoked at most once even under a race (atomic claim).
    """

    def __init__(
        self,
        store: CheckpointStore,
        *,
        run_id: str,
        node_id: str,
        node_version: str = "1",
        clock=time.time,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._node_id = node_id
        self._node_version = node_version
        self._clock = clock
        self.write_count = 0
        self._locks: dict[str, asyncio.Lock] = {}

    async def write(
        self,
        input_state: dict[str, Any],
        logical_operation_name: str,
        payload: Any,
        effect_fn: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        key = execution_key(
            self._run_id,
            self._node_id,
            self._node_version,
            input_state,
            logical_operation_name,
        )
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        async with lock:
            existing = await self._store.get_effect(key)
            if existing is not None:
                _log.info("idempotent hit for %s: returning recorded result", key)
                return existing.result_json
            result = await effect_fn(payload)
            self.write_count += 1
            await self._store.record_effect(
                EffectRecord(
                    execution_key=key,
                    run_id=self._run_id,
                    node_id=self._node_id,
                    node_version=self._node_version,
                    status="done",
                    result_json=result if isinstance(result, dict) else {"value": result},
                    created_at=self._clock(),
                )
            )
            return result
