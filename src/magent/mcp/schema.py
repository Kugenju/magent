"""JSON-Schema (subset) -> pydantic input models for MCP tools (phase 10).

The converter intentionally covers the schema shapes MCP servers commonly
emit and *falls back to untyped arguments* for anything else. A fallback is
always explicit: the loader records the schema mode in the toolset snapshot
(absent / typed / untyped) instead of failing an otherwise healthy tool.

Supported subset (hardened against real-world pydantic/FastMCP servers in P10.2):

- primitives (string/integer/number/boolean/null), enums via ``Literal``;
- arrays of primitives/enums (incl. ``items.$ref`` into ``$defs``);
- objects (recursive model construction; missing ``type`` with ``properties``
  still parses as an object);
- ``$defs`` + internal ``#/`` pointers (pydantic always wraps its enums and
  nested models this way - treating ``$ref`` as exotic made real servers
  silently untyped), with a resolution-depth cap against cycles;
- strict optionality pattern ``anyOf: [S, {"type": "null"}]`` (pydantic
  ``Optional[X]``) — everything else (true unions, ``allOf``/``oneOf``,
  ``if``/``not``, unresolvable refs) degrades to ``untyped`` mode where
  arguments pass through as plain dicts.
"""

from __future__ import annotations

import keyword
import re
from typing import Any, Literal, Mapping, Optional
from typing import Literal as LiteralAlias  # noqa: F401 - readability re-export

from pydantic import BaseModel, Field, create_model

# Modes recorded in the toolset snapshot.
SCHEMA_MODE_ABSENT = "absent"
SCHEMA_MODE_TYPED = "typed"
SCHEMA_MODE_UNTYPED = "untyped"

_PRIMITIVES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "null": type(None),
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

# Names that would shadow pydantic machinery even though they look like plain
# identifiers; using them as field names would break model construction.
_RESERVED_FIELDS = frozenset(
    name for name in dir(BaseModel) if not name.startswith("__")
)

_REF_DEFS = "#/$defs/"
_MAX_DEPTH = 6


def _resolve_ref(ref: Any, defs: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Resolve an internal ``#/`` pointer against the root ``$defs`` (or ``None``)."""
    if not isinstance(ref, str) or not ref.startswith(_REF_DEFS):
        return None
    if not isinstance(defs, Mapping):
        return None
    name = ref[len(_REF_DEFS):].rsplit("/", 1)[-1]
    target = defs.get(name)
    return target if isinstance(target, Mapping) else None


def _pascal_class_name(tool_name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", tool_name).strip("_")
    parts = [p for p in stem.split("_") if p]
    stem = "".join(p[:1].upper() + p[1:] for p in parts) or "Mcp"
    return f"Args{stem}"


def _field_name_ok(name: str) -> bool:
    return (
        bool(_IDENTIFIER_RE.match(name))
        and not keyword.iskeyword(name)
        and name not in _RESERVED_FIELDS
        and not name.startswith("_")
    )


def _bare_annotation(schema: Mapping[str, Any]) -> Any | None:
    """Annotation without arrangement (used for array items).

    ``None`` means "unsupported or complex" and triggers the fallback.
    """
    if not isinstance(schema, Mapping):
        return None
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        kinds = {type(v) for v in enum}
        if len(kinds) == 1 and kinds.pop() in (str, int, bool):
            return LiteralAlias[tuple(enum)]  # type: ignore[valid-type]
        return None
    t = schema.get("type")
    if t in _PRIMITIVES:
        return _PRIMITIVES[t]
    return None


def _annotation_for_schema(
    schema: Mapping[str, Any],
    class_stem: str,
    depth: int,
    defs: Mapping[str, Any],
) -> Any | None:
    """Best-effort annotation for one schema node; ``None`` means unsupported."""
    if not isinstance(schema, Mapping) or depth > _MAX_DEPTH:
        return None

    # Internal reference (pydantic's universal shape for enums/nested models).
    if "$ref" in schema:
        resolved = _resolve_ref(schema.get("$ref"), defs)
        if resolved is None:
            return None
        return _annotation_for_schema(resolved, class_stem, depth + 1, defs)

    # Strict optionality pattern: exactly one non-null branch plus null
    # (pydantic Optional[X]). Optionality itself is resolved by _build_model
    # (field not in "required"); return the branch annotation as-is.
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        branches = list(any_of)
        null_idx = [
            i
            for i, branch in enumerate(branches)
            if isinstance(branch, Mapping)
            and branch.get("type") == "null"
            and "enum" not in branch
            and len(branch) <= 2
        ]
        if len(branches) == 2 and len(null_idx) == 1:
            other = branches[1 - null_idx[0]]
            return _annotation_for_schema(other, class_stem, depth + 1, defs)
        return None

    enum_ann = _bare_annotation(schema)
    if enum_ann is not None:
        return enum_ann

    t = schema.get("type")

    if t == "array":
        items = schema.get("items")
        if items is None:
            return list[Any]  # type: ignore[valid-type]
        if isinstance(items, Mapping):
            if "$ref" in items:
                item_ann = _annotation_for_schema(
                    items, f"{class_stem}_item", depth + 1, defs
                )
                if item_ann is None:
                    return None
                return list[item_ann]  # type: ignore[valid-type]
            item_ann = _bare_annotation(items)
            if item_ann is None:
                return None
            return list[item_ann]  # type: ignore[valid-type]
        return None

    if t in _PRIMITIVES:
        return _PRIMITIVES[t]

    if t == "object":
        props = schema.get("properties")
        if not isinstance(props, Mapping):
            return dict[str, Any]
        return _build_model(props, schema, class_stem, depth + 1, defs)

    # Missing type but plain properties -> still an object.
    if t is None and isinstance(schema.get("properties"), Mapping):
        props = schema.get("properties")
        assert isinstance(props, Mapping)  # narrowed above
        return _build_model(props, schema, class_stem, depth + 1, defs)

    return None


def _build_model(
    properties: Mapping[str, Any],
    schema: Mapping[str, Any],
    class_stem: str,
    depth: int,
    defs: Mapping[str, Any],
) -> type[BaseModel] | None:
    """Build a dynamic pydantic model from object ``properties`` or ``None``."""
    raw_required = schema.get("required")
    if not isinstance(raw_required, list):
        raw_required = []
    required_set = {r for r in raw_required if isinstance(r, str)}

    fields: dict[str, tuple[Any, Any]] = {}
    for key, prop in properties.items():
        prop_name = str(key)
        if not isinstance(prop, Mapping) or not _field_name_ok(prop_name):
            return None
        if "allOf" in prop or "oneOf" in prop or "not" in prop or "if" in prop:
            return None
        if isinstance(prop.get("anyOf"), list) and len(prop["anyOf"]) != 2:
            return None  # true unions stay untyped
        ann = _annotation_for_schema(prop, f"{class_stem}_{prop_name}", depth, defs)
        if ann is None:
            return None
        desc = prop.get("description")
        description = desc if isinstance(desc, str) and desc else None
        if prop_name in required_set:
            default_spec: Any = (
                Field(...) if description is None else Field(..., description=description)
            )
        elif "default" in prop:
            default_value = prop["default"]
            default_spec = (
                Field(default=default_value)
                if description is None
                else Field(default=default_value, description=description)
            )
        else:
            if description is None:
                default_spec = None  # optional without description
            else:
                default_spec = Field(default=None, description=description)
            ann = Optional[ann]
        fields[prop_name] = (ann, default_spec)

    name = f"{_pascal_class_name(class_stem)}{'' if depth == 0 else depth}"
    try:
        model: type[BaseModel] = create_model(name, __base__=BaseModel, **fields)  # type: ignore[call-overload]
    except Exception:
        return None
    return model


def build_input_model(
    tool_name: str,
    input_schema: Mapping[str, Any] | None,
) -> tuple[type[BaseModel] | None, str]:
    """Convert an MCP ``inputSchema`` to a validating pydantic model.

    Returns ``(model, mode)`` where ``mode`` is one of:

    - ``SCHEMA_MODE_ABSENT``  — no schema provided; arguments pass as-is.
    - ``SCHEMA_MODE_TYPED``   — a pydantic model was generated; args validated.
    - ``SCHEMA_MODE_UNTYPED`` — conversion fell back; args pass as raw dict.

    Argument validation happens in the registry (via ``input_model``), exactly
    like for local tools - never inside this function.
    """
    if input_schema is None:
        return None, SCHEMA_MODE_ABSENT
    if not isinstance(input_schema, Mapping):
        return None, SCHEMA_MODE_UNTYPED
    if not input_schema:
        return None, SCHEMA_MODE_ABSENT

    defs_raw = input_schema.get("$defs")
    defs: Mapping[str, Any] = defs_raw if isinstance(defs_raw, Mapping) else {}

    # Root-level reference (pydantic's schema for a bare aliased model).
    root: Mapping[str, Any] = input_schema
    if "$ref" in input_schema:
        resolved = _resolve_ref(input_schema.get("$ref"), defs)
        if resolved is None:
            return None, SCHEMA_MODE_UNTYPED
        root = resolved

    top_type = root.get("type")
    properties = root.get("properties")
    if top_type not in (None, "object") or not isinstance(properties, Mapping) or not properties:
        return None, SCHEMA_MODE_UNTYPED

    # Root-level unions/compositions stay unsupported (per-property strict
    # optional-anyOf handling lives in ``_annotation_for_schema``).
    exotic = any(k in root for k in ("allOf", "anyOf", "oneOf", "if", "not"))
    if exotic:
        return None, SCHEMA_MODE_UNTYPED

    model = _build_model(properties, root, tool_name, 0, defs)
    if model is None:
        return None, SCHEMA_MODE_UNTYPED
    return model, SCHEMA_MODE_TYPED


def dump_arguments(arguments: Any) -> dict[str, Any]:
    """Normalize registry-side arguments into the dict shape MCP expects."""
    if isinstance(arguments, BaseModel):
        dumped = arguments.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(arguments, dict):
        return dict(arguments)
    # The registry only ever hands models or dicts; anything else is a bug.
    raise TypeError(
        f"mcp arguments must be BaseModel or dict, got {type(arguments).__name__}"
    )
