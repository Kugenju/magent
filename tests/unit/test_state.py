from __future__ import annotations

import pytest

from magent import merge_updates, StateUpdateError
from pydantic import BaseModel, Field


class DemoState(BaseModel):
    value: int = 0
    messages: list[str] = Field(default_factory=list)


def test_merge_applies_updates_and_returns_new_instance():
    original = DemoState()
    updated = merge_updates(original, {"value": 5})
    assert updated.value == 5
    assert original.value == 0


def test_merge_rejects_unknown_field():
    with pytest.raises(StateUpdateError):
        merge_updates(DemoState(), {"unknown": 1})


def test_merge_rejects_type_mismatch():
    with pytest.raises(StateUpdateError):
        merge_updates(DemoState(), {"value": "not-an-int"})


def test_list_default_factory_is_not_shared():
    original = DemoState()
    updated = merge_updates(original, {"messages": original.messages + ["x"]})
    assert updated.messages == ["x"]
    assert original.messages == []
