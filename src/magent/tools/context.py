"""Read-only context handed to a tool at invocation time (phase 6).

The context intentionally exposes only what a tool needs: the run/node
identity, the tool version, a logger, an optional cancellation event, and a
*controlled* side-effect sink. It never exposes the executor, the scheduler or
raw database handles.
"""

from __future__ import annotations

from typing import Any, Callable

from magent.checkpoint.idempotency import SideEffectSink


class ToolContext:
    def __init__(
        self,
        *,
        run_id: str,
        node_id: str,
        tool_version: str = "1",
        logger=None,
        cancel_event: Any = None,
        side_effect_sink: SideEffectSink | None = None,
        emit: Callable[[str, dict], Any] | None = None,
    ) -> None:
        self._run_id = run_id
        self._node_id = node_id
        self._tool_version = tool_version
        self._logger = logger
        self._cancel_event = cancel_event
        self._sink = side_effect_sink
        self._emit = emit

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def tool_version(self) -> str:
        return self._tool_version

    @property
    def logger(self):
        return self._logger

    @property
    def cancel_event(self):
        return self._cancel_event

    @property
    def side_effect_sink(self) -> SideEffectSink | None:
        return self._sink

    def is_cancelled(self) -> bool:
        ev = self._cancel_event
        return ev is not None and getattr(ev, "is_set", lambda: False)()

    def emit(self, topic: str, payload: dict) -> Any:
        if self._emit is not None:
            return self._emit(topic, payload)
        return None
