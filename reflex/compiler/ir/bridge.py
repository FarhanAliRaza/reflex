"""Phase-1 bridge: walk a finalized Component tree, emit complete IR.

This is the **only** place Python code touches Component / Var objects on
the compile path. After ``component_to_ir(...)`` returns, the IR carries
every piece of data the Rust codegen needs — Rust phase 2 walks the bytes
and never calls back into Python.

Coverage matches what ``reflex_pyread::pyo3_reader`` currently extracts:

* Component dispatch: ``Bare``, ``Fragment``, ``Cond``, ``Foreach``,
  ``Match``, generic ``Element``.
* Values: ``Var`` → ``js_expr`` with full ``VarData`` payload; ``None`` /
  ``bool`` / ``int`` / ``float`` / ``str`` → ``Literal``; complex Python
  values (dicts, lists, ``EventChain``) → wrapped via
  ``LiteralVar.create`` so they become a ``Var`` with the correct JS
  expression.
* ``Foreach``: materializes the body via ``_render() →
  render_component()`` so the iter-var arg is correctly typed. **This
  is phase-1 work** — without it Rust would have to call back.
* Events: each handler stringified via the same ``LiteralVar.create``
  path used for complex values.
* Page-level: ``component_imports`` (module → alias spec),
  ``state_bindings`` (``StateContexts.<key>``), ``needs_ref`` flag.

The bridge is deliberately straight-line Python — no clever caching,
no class hierarchy. Inlined helpers and tight loops produce predictable
per-node cost (~3 µs/node on the bench app). For a meaningful speedup
over the current pyread path the win has to come from staying inside
CPython memory the whole walk; the bridge is what enforces that.
"""

from __future__ import annotations

import re
from typing import Any

import msgpack

from reflex.compiler.ir import schema as _schema


# Module-level cached classes, looked up once. Avoids the per-call
# ``isinstance`` import dance the Rust pyread pays via ``PyRefs``.
def _get_classes() -> tuple[Any, Any, Any]:
    from reflex_base.utils.format import format_library_name
    from reflex_base.vars.base import LiteralVar, Var

    return Var, LiteralVar, format_library_name


_VAR: Any = None
_LITERAL_VAR: Any = None
_FORMAT_LIB: Any = None


def _ensure_classes() -> None:
    global _VAR, _LITERAL_VAR, _FORMAT_LIB
    if _VAR is None:
        _VAR, _LITERAL_VAR, _FORMAT_LIB = _get_classes()


_STATE_PREFIX = "reflex___state____state__"
_STATE_SUFFIX = "_state"

# Local-bind schema constants — module-level attribute lookups on the
# hot path cost ~5x more than a global int lookup.
_VAL_JS_EXPR = _schema.VALUE_JS_EXPR
_VAL_LITERAL = _schema.VALUE_LITERAL
_LIT_NULL = _schema.LITERAL_NULL
_LIT_BOOL = _schema.LITERAL_BOOL
_LIT_INT = _schema.LITERAL_INT
_LIT_FLOAT = _schema.LITERAL_FLOAT
_LIT_STR = _schema.LITERAL_STR
_COMP_TEXT = _schema.COMPONENT_TEXT
_COMP_EXPR = _schema.COMPONENT_EXPR
_COMP_FRAGMENT = _schema.COMPONENT_FRAGMENT
_COMP_COND = _schema.COMPONENT_COND
_COMP_FOREACH = _schema.COMPONENT_FOREACH
_COMP_MATCH = _schema.COMPONENT_MATCH
_COMP_ELEMENT = _schema.COMPONENT_ELEMENT
_SCHEMA_VERSION = _schema.SCHEMA_VERSION

# Pre-compiled regex for state identifier scanning.  Word boundaries on
# both sides ensure prefixes/suffixes inside larger identifiers are not
# matched. Dispatching this through the C-level ``re`` engine is ~10x
# faster than the manual character-by-character scan it replaces.
_STATE_IDENT_RE = re.compile(
    rf"(?<!\w){re.escape(_STATE_PREFIX)}\w*{re.escape(_STATE_SUFFIX)}(?!\w)"
)


def _find_state_idents(expr: str) -> list[str]:
    """Find state identifier substrings in a JS expression.

    Matches substrings of the form
    ``reflex___state____state__<body>_state`` with word boundaries on
    both sides.

    Args:
        expr: a JS expression string from a Var ``_js_expr``.

    Returns:
        Matched identifiers in order of first appearance.
    """
    return _STATE_IDENT_RE.findall(expr)


# -----------------------------------------------------------------------------
# Page-level harvest state — populated as the walk visits nodes.
# -----------------------------------------------------------------------------


class _Harvest:
    """Per-page accumulator for module imports, state bindings, ref flag."""

    __slots__ = (
        "_component_imports_seen",
        "_state_bindings_seen",
        "component_imports",
        "needs_ref",
        "state_bindings",
    )

    def __init__(self) -> None:
        self.component_imports: list[tuple[str, str]] = []
        self._component_imports_seen: set[tuple[str, str]] = set()
        self.state_bindings: list[str] = []
        self._state_bindings_seen: set[str] = set()
        self.needs_ref: bool = False

    def add_import(self, module: str, alias_spec: str) -> None:
        key = (module, alias_spec)
        if key not in self._component_imports_seen:
            self._component_imports_seen.add(key)
            self.component_imports.append(key)

    def scan_expr(self, expr: str) -> None:
        for ident in _find_state_idents(expr):
            if ident not in self._state_bindings_seen:
                self._state_bindings_seen.add(ident)
                self.state_bindings.append(ident)


# -----------------------------------------------------------------------------
# VarData → IR.
# -----------------------------------------------------------------------------


def _var_data_to_ir(var: Any, harvest: _Harvest) -> list:
    """Extract the full merged VarData for ``var`` as positional IR.

    Mirrors ``reflex_pyread::pyo3_reader::read_var_data``. Calls
    ``var._get_all_var_data()`` to fold inherited deps/imports/hooks,
    then unpacks each field to a primitive-only list-of-lists shape.

    Args:
        var: a Var instance whose VarData should be flattened.
        harvest: page-level accumulator updated with imports observed
            during the walk.

    Returns:
        Positional IR fragment matching the wire VarData shape:
        ``[hooks, imports, state, deps, position, components]``.
    """
    # Every Var defines `_get_all_var_data`; calling it directly avoids
    # the per-call hasattr probe + the secondary `_var_data` fallback
    # that only fires when subclassing without overriding (not on the
    # compile path).
    vd = var._get_all_var_data()
    if vd is None:
        # Return a fresh list each call — the IR list reaches msgpack
        # via `_value_to_ir(...)`, which doesn't mutate, but a shared
        # mutable sentinel is a latent footgun if a downstream consumer
        # ever tries to extend it.
        return [[], [], None, [], None, []]

    hooks_raw = vd.hooks
    hooks = list(hooks_raw) if hooks_raw else []

    imports_out: list[list[str]] = []
    raw_imports = vd.imports or ()
    if isinstance(raw_imports, dict):
        raw_imports = raw_imports.items()
    for entry in raw_imports:
        module, ivs = entry
        module = _FORMAT_LIB(module) if module else ""
        if not module:
            continue
        for iv in ivs:
            tag = iv.tag or ""
            alias = iv.alias or ""
            # Schema is (module, name) length-2 pairs; encode aliases
            # inline as "name as alias" the same way the page-level
            # component_imports harvest does.
            name = tag if not alias else f"{tag} as {alias}"
            imports_out.append([module, name])
            if tag:
                # Page-level harvest used by the runtime-import emitter.
                harvest.add_import(module, name)

    state = vd.state or None

    deps_out: list[str] = []
    if vd.deps:
        for d in vd.deps:
            js_expr = getattr(d, "_js_expr", None)
            deps_out.append(js_expr if js_expr is not None else str(d))

    return [hooks, imports_out, state, deps_out, None, []]


# Shared sentinel for value-IR fragments that need an empty VarData
# slot. DO NOT mutate — downstream consumers reach this list through
# msgpack which treats it as read-only.
_schema_EMPTY_VAR_DATA: list = [[], [], None, [], None, []]


# -----------------------------------------------------------------------------
# Value → IR.
# -----------------------------------------------------------------------------


def _value_to_ir(value: Any, harvest: _Harvest) -> list:
    """Convert a prop / event-handler value to a Value IR fragment.

    Args:
        value: a prop value (``Var``, primitive, or complex Python object).
        harvest: page-level accumulator that records state idents and
            imports observed in any ``Var`` traversed.

    Returns:
        Positional IR list-of-lists, ready for msgpack packing.
    """
    # Var is by far the most common case — check first.
    if isinstance(value, _VAR):
        expr = value._js_expr
        harvest.scan_expr(expr)
        return [_VAL_JS_EXPR, expr, _var_data_to_ir(value, harvest)]
    # None comes next: bare ``None`` props appear far more often than
    # bool/int/float literals on real pages.
    if value is None:
        return [_VAL_LITERAL, [_LIT_NULL]]
    # Use `type(...) is X` instead of `isinstance` — none of these have
    # user-defined subclasses on the compile path, and direct identity
    # comparison avoids walking the MRO on every value.
    t = type(value)
    if t is bool:
        return [_VAL_LITERAL, [_LIT_BOOL, value]]
    if t is int:
        return [_VAL_LITERAL, [_LIT_INT, value]]
    if t is float:
        return [_VAL_LITERAL, [_LIT_FLOAT, value]]
    if t is str:
        return [_VAL_LITERAL, [_LIT_STR, value]]
    # Complex Python value: wrap through LiteralVar so the JS string is
    # built by Reflex's own formatter, then treat as a Var.
    wrapped = _LITERAL_VAR.create(value)
    if isinstance(wrapped, _VAR):
        expr = wrapped._js_expr
        harvest.scan_expr(expr)
        return [_VAL_JS_EXPR, expr, _var_data_to_ir(wrapped, harvest)]
    return [_VAL_LITERAL, [_LIT_STR, str(wrapped)]]


# -----------------------------------------------------------------------------
# Event handler → IR.
# -----------------------------------------------------------------------------


def _event_to_ir(trigger: str, handler: Any, harvest: _Harvest) -> list:
    """Stringify an event handler chain to ``[trigger, expr, var_data]``."""
    if isinstance(handler, _VAR):
        expr = handler._js_expr
        harvest.scan_expr(expr)
        return [trigger, expr, _var_data_to_ir(handler, harvest)]
    wrapped = _LITERAL_VAR.create(handler)
    if isinstance(wrapped, _VAR):
        expr = wrapped._js_expr
        harvest.scan_expr(expr)
        return [trigger, expr, _var_data_to_ir(wrapped, harvest)]
    return [trigger, str(wrapped), _schema_EMPTY_VAR_DATA]


# -----------------------------------------------------------------------------
# Element props → IR.
# -----------------------------------------------------------------------------


def _props_to_ir(c: Any, harvest: _Harvest) -> list:
    """Extract every prop the Rust pyread reads: declared, identity, custom."""
    out: list[list] = []
    try:
        prop_names = c.get_props()
    except AttributeError:
        prop_names = ()
    for name in prop_names:
        v = getattr(c, name, None)
        if v is None:
            continue
        attr_name = name.removesuffix("_")
        out.append([attr_name, _value_to_ir(v, harvest)])
    for name in ("key", "id", "class_name"):
        v = getattr(c, name, None)
        if v is None:
            continue
        if isinstance(v, str) and v == "":
            continue
        if name == "id":
            harvest.needs_ref = True
        out.append([name, _value_to_ir(v, harvest)])
    ca = getattr(c, "custom_attrs", None)
    if ca:
        for k, v in ca.items():
            out.append([str(k), _value_to_ir(v, harvest)])
    return out


# -----------------------------------------------------------------------------
# Component dispatch.
# -----------------------------------------------------------------------------


SYNTHETIC_LOC = [0, 0, 0]


def _bare_to_ir(c: Any, harvest: _Harvest) -> list:
    contents = getattr(c, "contents", None)
    if contents is None:
        return [_COMP_TEXT, "", 0, SYNTHETIC_LOC]
    if isinstance(contents, _VAR):
        expr = contents._js_expr
        harvest.scan_expr(expr)
        # JS string literal → text node; otherwise expression node.
        decoded = _decode_js_string(expr)
        if decoded is not None:
            return [_COMP_TEXT, decoded, 0, SYNTHETIC_LOC]
        return [
            _COMP_EXPR,
            [_VAL_JS_EXPR, expr, _var_data_to_ir(contents, harvest)],
            0,
            SYNTHETIC_LOC,
        ]
    return [_COMP_TEXT, str(contents), 0, SYNTHETIC_LOC]


def _decode_js_string(expr: str) -> str | None:
    """Decode a JS string literal ``"..."`` produced by ``LiteralVar.create``.

    Reflex's ``LiteralVar.create(str)`` always emits JSON-encoded
    strings, so the only escape sequences we have to handle are the
    JSON-compatible ones. Hand-rolling the decoder avoids spinning a
    fresh ``json.JSONDecoder`` per Bare node — measurably faster on
    text-heavy pages.

    Args:
        expr: a JS expression string from a Var ``_js_expr``.

    Returns:
        Decoded string contents if ``expr`` is a valid JS string
        literal, ``None`` otherwise.
    """
    n = len(expr)
    if n < 2 or expr[0] != '"' or expr[-1] != '"':
        return None
    # Fast path: no backslash escapes → just strip the quotes.
    if "\\" not in expr:
        return expr[1:-1]
    # Slow path: decode JSON-style escapes manually.
    out: list[str] = []
    i = 1
    end = n - 1
    while i < end:
        ch = expr[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= end:
            return None
        esc = expr[i]
        if esc == '"':
            out.append('"')
        elif esc == "\\":
            out.append("\\")
        elif esc == "/":
            out.append("/")
        elif esc == "n":
            out.append("\n")
        elif esc == "r":
            out.append("\r")
        elif esc == "t":
            out.append("\t")
        elif esc == "b":
            out.append("\b")
        elif esc == "f":
            out.append("\f")
        elif esc == "u":
            if i + 5 > end:
                return None
            try:
                out.append(chr(int(expr[i + 1 : i + 5], 16)))
            except ValueError:
                return None
            i += 4
        else:
            # Unknown escape — bail rather than risk a wrong decode.
            return None
        i += 1
    return "".join(out)


def _children_to_ir(c: Any, harvest: _Harvest) -> list:
    children = c.children
    if not children:
        return []
    # Pre-allocate to avoid list-grow during the comprehension.
    return [_component_to_ir(ch, harvest) for ch in children]


def _fragment_to_ir(c: Any, harvest: _Harvest) -> list:
    return [_COMP_FRAGMENT, _children_to_ir(c, harvest), 0, SYNTHETIC_LOC]


def _cond_to_ir(c: Any, harvest: _Harvest) -> list:
    test = _value_to_ir(c.cond, harvest)
    children = c.children
    if children:
        then_ir = _component_to_ir(children[0], harvest)
        else_ir = _component_to_ir(children[1], harvest) if len(children) > 1 else None
    else:
        then_ir = None
        else_ir = None
    return [_COMP_COND, test, then_ir, else_ir, 0, SYNTHETIC_LOC]


def _foreach_to_ir(c: Any, harvest: _Harvest) -> list:
    # Phase-1 critical work: materialize body via _render() so the
    # iter-var arg has the correct type (ArrayCastedVar / ObjectVar).
    # Without this Rust would have to call _render() during phase 2.
    iter_tag = c._render()
    body_component = iter_tag.render_component()
    body_ir = _component_to_ir(body_component, harvest)
    iter_value = _value_to_ir(c.iterable, harvest)
    return [_COMP_FOREACH, iter_value, body_ir, 0, SYNTHETIC_LOC]


def _match_to_ir(c: Any, harvest: _Harvest) -> list:
    test = _value_to_ir(c.cond, harvest)
    arms: list[list] = []
    default: list | None = None
    cases = getattr(c, "match_cases", None) or ()
    for case_entry in cases:
        entries = list(case_entry)
        body_component = entries[-1]
        body_ir = _component_to_ir(body_component, harvest)
        case_vals = [_value_to_ir(v, harvest) for v in entries[:-1]]
        for cv in case_vals:
            arms.append([cv, body_ir])
    default_component = getattr(c, "default", None)
    if default_component is not None:
        default = _component_to_ir(default_component, harvest)
    return [_COMP_MATCH, test, arms, default, 0, SYNTHETIC_LOC]


def _element_to_ir(c: Any, harvest: _Harvest) -> list:
    cls = type(c)
    raw_tag = c.tag
    library = c.library
    alias = c.alias
    is_global = bool(c._is_tag_in_global_scope)

    # Tag resolution mirrors reflex_pyread::resolve_tag_symbol:
    # prefer alias, then tag; if library is None and the tag is in
    # global JS scope, quote it ("title", "meta") for jsx() emit.
    raw_name = alias or (raw_tag or "")
    trimmed = raw_name.strip('"') if type(raw_name) is str else str(raw_name).strip('"')
    if library is None and is_global and trimmed:
        emit_tag = f'"{trimmed}"'
    else:
        emit_tag = trimmed or cls.__name__

    # NOTE: per-element import harvest used to live here. It's now
    # done once per page in ``component_to_ir`` via
    # ``component._get_all_imports()`` — that walks hooks' VarData and
    # ``_get_components_in_props()`` too, so ColorModeContext / Code
    # (referenced from markdown component_map closures) / etc. land in
    # the page module's import block even though no Element visits
    # them directly.
    tag = emit_tag
    props = _props_to_ir(c, harvest)
    events: list[list] = []
    et = c.event_triggers
    if et:
        for trigger, handler in et.items():
            events.append(_event_to_ir(trigger, handler, harvest))
    hooks: list[list] = []  # phase-1 doesn't aggregate hooks per-element
    children = _children_to_ir(c, harvest)
    return [
        _COMP_ELEMENT,
        tag,
        props,
        children,
        events,
        hooks,
        0,
        SYNTHETIC_LOC,
    ]


# Dispatch is keyed on the class object so the per-call hot path is a
# single dict lookup with `u64` hashes — no `__name__` descriptor walk.
# The first encounter with a class falls back to a string-keyed lookup
# (so we don't have to eagerly import Bare/Fragment/... and risk a
# circular import), then memoizes the result.
_DISPATCH_BY_NAME: dict[str, Any] = {
    "Bare": _bare_to_ir,
    "Fragment": _fragment_to_ir,
    "Cond": _cond_to_ir,
    "Foreach": _foreach_to_ir,
    "Match": _match_to_ir,
}
_DISPATCH: dict[type, Any] = {}


def _component_to_ir(c: Any, harvest: _Harvest) -> list:
    cls = type(c)
    fn = _DISPATCH.get(cls)
    if fn is None:
        fn = _DISPATCH_BY_NAME.get(cls.__name__, _element_to_ir)
        _DISPATCH[cls] = fn
    return fn(c, harvest)


# -----------------------------------------------------------------------------
# Public entry points.
# -----------------------------------------------------------------------------


def component_to_ir(
    component: Any, *, extra_imports: Any = None
) -> tuple[list, _Harvest]:
    """Walk a finalized Component tree, return ``(component_ir, harvest)``.

    Args:
        component: a fully-constructed Component (output of
            ``compile_unevaluated_page``, with theme + Fragment wrap).
        extra_imports: optional ``ParsedImportDict`` whose entries get
            merged into ``harvest.component_imports``. Pass the
            *pre-memoize* ``_get_all_imports()`` here when the tree the
            bridge sees has had memo wrappers substituted in — the
            wrappers carry no imports from the inner subtree, so the
            page module would otherwise be missing ``ColorModeContext``,
            ``RadixThemesCode``, etc.

    Returns:
        ``(component_ir, harvest)`` — the IR list-of-lists ready for
        :func:`page_to_ir`, plus the page-level harvest accumulator.
    """
    _ensure_classes()
    harvest = _Harvest()
    ir = _component_to_ir(component, harvest)
    if extra_imports is None:
        extra_imports = component._get_all_imports()
    _merge_imports_into_harvest(extra_imports, harvest)
    return ir, harvest


# React-runtime symbols the Rust page emitter declares itself —
# component-level imports that name these would produce duplicate
# `import { Fragment, ... } from "react"` lines.
_REACT_RUNTIME_BUILTINS = frozenset({"Fragment", "useContext", "useRef"})


def _merge_imports_into_harvest(raw: Any, harvest: _Harvest) -> None:
    """Fold a ``_get_all_imports()`` result into ``harvest.component_imports``.

    Mirrors ``import_alias_for``'s dotted-name handling and skips the
    React-runtime built-ins the Rust emitter declares itself.

    Args:
        raw: a ``ParsedImportDict`` (module → list of ``ImportVar``).
        harvest: page-level accumulator to populate.
    """
    if not raw:
        return
    for lib, ivs in raw.items():
        module = _FORMAT_LIB(lib) if lib else ""
        if not module:
            continue
        for iv in ivs:
            tag = iv.tag or ""
            alias = iv.alias or ""
            if not tag and not alias:
                continue
            # `tag.partition(".")` avoids allocating the 2-element list
            # that `tag.split(".", 1)` would produce.
            tag_root = tag.partition(".")[0] if tag else ""
            alias_root = alias.partition(".")[0] if alias else ""
            if not tag_root and not alias_root:
                continue
            if module == "react" and tag_root in _REACT_RUNTIME_BUILTINS:
                continue
            if alias_root and tag_root and alias_root != tag_root:
                harvest.add_import(module, f"{tag_root} as {alias_root}")
            elif tag_root:
                harvest.add_import(module, tag_root)
            elif alias_root:
                harvest.add_import(module, alias_root)


def page_to_ir(
    *,
    route: str,
    component: Any,
    title: str | None = None,
    meta: list[tuple[str, str]] | None = None,
    extra_imports: Any = None,
) -> bytes:
    """Build a complete Page IR and pack it to msgpack bytes.

    Args:
        route: URL path the page is served at.
        component: the finalized root Component (after theme + wrap).
        title: optional document title.
        meta: optional list of ``(name, content)`` <meta> entries.
        extra_imports: optional ``ParsedImportDict`` to fold into the
            page module's import block. Use this to pass a pre-memoize
            ``_get_all_imports()`` so the import block stays correct
            after :func:`reflex.compiler.rust_memo.walk_and_memoize`
            substitutes memo wrappers into the tree.

    Returns:
        msgpack-packed bytes. Hand this directly to phase-2 Rust.
    """
    component_ir, harvest = component_to_ir(component, extra_imports=extra_imports)
    page_ir = [
        _SCHEMA_VERSION,
        route,
        component_ir,
        title,
        list(meta or ()),
        [],  # source_files
        [list(p) for p in harvest.component_imports],
        list(harvest.state_bindings),
        bool(harvest.needs_ref),
    ]
    return msgpack.packb(page_ir, use_bin_type=True)
