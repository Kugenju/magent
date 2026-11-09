"""Phase 10 — MCP input-schema (subset) conversion tests."""

from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel

from magent.mcp.schema import (
    SCHEMA_MODE_ABSENT,
    SCHEMA_MODE_TYPED,
    SCHEMA_MODE_UNTYPED,
    build_input_model,
    dump_arguments,
)


async def test_absent_schema():
    model, mode = build_input_model("t", None)
    assert model is None and mode == SCHEMA_MODE_ABSENT
    model, mode = build_input_model("t", {})
    assert model is None and mode == SCHEMA_MODE_ABSENT


async def test_typed_simple_object():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
        "required": ["a"],
    }
    model, mode = build_input_model("echo", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    instance = model.model_validate({"a": 1, "b": "x"})
    assert instance.a == 1 and instance.b == "x"
    # required field enforcement stays with pydantic validation
    with pytest.raises(Exception):
        model.model_validate({"b": "x"})


async def test_typed_optional_with_default():
    schema = {
        "type": "object",
        "properties": {
            "n": {"type": "integer", "default": 7},
            "flag": {"type": "boolean"},
        },
        "required": [],
    }
    model, mode = build_input_model("opts", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    instance = model.model_validate({})
    assert instance.n == 7 and instance.flag is None


async def test_typed_enum_becomes_literal():
    schema = {
        "type": "object",
        "properties": {"color": {"type": "string", "enum": ["red", "green"]}},
        "required": ["color"],
    }
    model, mode = build_input_model("paint", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    data = model.model_validate({"color": "red"})
    assert data.color == "red"
    with pytest.raises(Exception):
        model.model_validate({"color": "blue"})


async def test_typed_list_of_primitives():
    schema = {
        "type": "object",
        "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
    }
    model, mode = build_input_model("pick", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    instance = model.model_validate({"ids": [1, 2, 3]})
    assert instance.ids == [1, 2, 3]


async def test_typed_nested_object():
    schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "object",
                "properties": {"host": {"type": "string"}, "port": {"type": "integer"}},
                "required": ["host"],
            }
        },
        "required": ["target"],
    }
    model, mode = build_input_model("connect", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    data = model.model_validate({"target": {"host": "h", "port": 1}})
    assert data.target.host == "h" and data.target.port == 1
    with pytest.raises(Exception):
        model.model_validate({"target": {"port": 1}})


async def test_fallback_untyped_on_exotic_composition():
    schema = {
        "type": "object",
        "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "integer"}]}},
    }
    model, mode = build_input_model("wild", schema)
    assert model is None and mode == SCHEMA_MODE_UNTYPED


async def test_fallback_untyped_on_invalid_field_name():
    cases = [
        {"1bad": {"type": "string"}},
        {"class": {"type": "string"}},
        {"_secret": {"type": "string"}},
        {"model_fields": {"type": "string"}},
    ]
    for properties in cases:
        schema = {"type": "object", "properties": properties}
        model, mode = build_input_model("badnames", schema)
        assert model is None, properties
        assert mode == SCHEMA_MODE_UNTYPED


async def test_fallback_untyped_on_nested_array():
    schema = {
        "type": "object",
        "properties": {"matrix": {"type": "array", "items": {"type": "array"}}},
    }
    model, mode = build_input_model("matrix", schema)
    assert model is None and mode == SCHEMA_MODE_UNTYPED


async def test_fallback_untyped_on_non_object_root():
    assert build_input_model("root", {"type": "string"})[1] == SCHEMA_MODE_UNTYPED
    assert build_input_model("root", {"type": "array"})[1] == SCHEMA_MODE_UNTYPED


async def test_fallback_untyped_on_ref():
    # An *unresolvable* root reference (non-$defs pointer) degrades to untyped.
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "$ref": "#/definitions/x",
    }
    model, mode = build_input_model("refs", schema)
    assert model is None and mode == SCHEMA_MODE_UNTYPED


async def test_defs_with_internal_ref_resolves_enums():
    """pydantic-style schema: $defs + $ref (real FastMCP shape)."""
    schema = {
        "type": "object",
        "$defs": {
            "Service": {
                "enum": ["osv", "nvd", "github"],
                "title": "Service",
                "type": "string",
            }
        },
        "properties": {
            "service": {"$ref": "#/$defs/Service"},
            "max_results": {"default": 5, "type": "integer"},
        },
        "required": ["service"],
        "title": "profile_queryArguments",
    }
    model, mode = build_input_model("profile_query", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    instance = model.model_validate({"service": "osv"})
    assert instance.service == "osv" and instance.max_results == 5
    with pytest.raises(Exception):
        model.model_validate({"service": "xml"})


async def test_defs_with_ref_used_in_array_items():
    schema = {
        "type": "object",
        "$defs": {
            "Service": {"enum": ["osv", "nvd"], "type": "string"},
        },
        "properties": {"services": {"items": {"$ref": "#/$defs/Service"}, "type": "array"}},
    }
    model, mode = build_input_model("batch", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    instance = model.model_validate({"services": ["osv", "nvd"]})
    assert instance.services == ["osv", "nvd"]


async def test_pydantic_optional_anyof_pattern_is_typed():
    """Optional[X] serializes as anyOf [X, null] -> typed optional."""
    schema = {
        "type": "object",
        "$defs": {"Service": {"enum": ["osv"], "type": "string"}},
        "properties": {
            "service": {"anyOf": [{"$ref": "#/$defs/Service"}, {"type": "null"}]},
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
    }
    model, mode = build_input_model("opts2", schema)
    assert mode == SCHEMA_MODE_TYPED and model is not None
    instance = model.model_validate({})
    assert instance.limit is None
    with pytest.raises(Exception):
        model.model_validate({"service": "xml"})
    model.model_validate({"service": "osv", "limit": 7}) is not None


async def test_true_union_anyof_stays_untyped():
    schema = {
        "type": "object",
        "properties": {
            "a": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        },
    }
    model, mode = build_input_model("union", schema)
    assert model is None and mode == SCHEMA_MODE_UNTYPED


async def test_unresolvable_internal_ref_stays_untyped():
    schema = {
        "type": "object",
        "$defs": {"Other": {"type": "string"}},
        "properties": {"a": {"$ref": "#/$defs/Missing"}},
    }
    model, mode = build_input_model("badref", schema)
    assert model is None and mode == SCHEMA_MODE_UNTYPED


async def test_fallback_untyped_when_root_type_missing_and_no_properties():
    model, mode = build_input_model("weird", {"foo": "bar"})
    assert model is None and mode == SCHEMA_MODE_UNTYPED


async def test_dump_arguments_variants():
    class Args(BaseModel):
        a: int

    assert dump_arguments(Args(a=1)) == {"a": 1}
    assert dump_arguments({"a": 2}) == {"a": 2}
    with pytest.raises(TypeError):
        dump_arguments(42)


async def test_freshly_generated_model_is_a_real_model():
    schema = {
        "type": "object",
        "properties": {"x": {"type": "number"}, "y": {"type": "null"}},
    }
    model, mode = build_input_model("geom", schema)
    assert mode == SCHEMA_MODE_TYPED
    assert model is not None and isinstance(model, type)
    assert issubclass(model, BaseModel)
    instance = model.model_validate({"x": 1.5, "y": None})
    assert isinstance(instance, BaseModel)
    _ = Optional[int]  # import kept for parity with typing helpers
