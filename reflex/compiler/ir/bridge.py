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


def _find_state_idents(expr: str) -> list[str]:
    """Port of reflex_pyread::find_state_idents.

    Finds substrings of the form
    ``reflex___state____state__<body>_state`` with word boundaries on
    both sides. Returns the matched idents in order of first appearance.
    """
    out: list[str] = []
    n = len(expr)
    i = 0
    plen = len(_STATE_PREFIX)
    while i < n:
        if expr.startswith(_STATE_PREFIX, i):
            if i > 0:
                prev = expr[i - 1]
                if prev.isalnum() or prev == "_":
                    i += 1
                    continue
            body_start = i + plen
            j = body_start
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            if j > body_start and expr[body_start:j].endswith(_STATE_SUFFIX):
                right_ok = j == n or not (expr[j].isalnum() or expr[j] == "_")
                if right_ok:
                    out.append(expr[i:j])
                    i = j
                    continue
        i += 1
    return out


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
    """
    vd = var._get_all_var_data() if hasattr(var, "_get_all_var_data") else None
    if vd is None:
        vd = getattr(var, "_var_data", None)
    if vd is None:
        return _schema_EMPTY_VAR_DATA

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
            tag = getattr(iv, "tag", None) or ""
            alias = getattr(iv, "alias", None) or ""
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
            deps_out.append(getattr(d, "_js_expr", None) or str(d))

    return [hooks, imports_out, state, deps_out, None, []]


_schema_EMPTY_VAR_DATA: list = [[], [], None, [], None, []]


# -----------------------------------------------------------------------------
# Value → IR.
# -----------------------------------------------------------------------------


def _value_to_ir(value: Any, harvest: _Harvest) -> list:
    """Convert a prop / event-handler value to a Value IR fragment."""
    if isinstance(value, _VAR):
        expr = value._js_expr
        harvest.scan_expr(expr)
        return [_schema.VALUE_JS_EXPR, expr, _var_data_to_ir(value, harvest)]
    if value is None:
        return [_schema.VALUE_LITERAL, [_schema.LITERAL_NULL]]
    # bool MUST come before int (bool is subclass of int in Python)
    if isinstance(value, bool):
        return [_schema.VALUE_LITERAL, [_schema.LITERAL_BOOL, value]]
    if isinstance(value, int):
        return [_schema.VALUE_LITERAL, [_schema.LITERAL_INT, value]]
    if isinstance(value, float):
        return [_schema.VALUE_LITERAL, [_schema.LITERAL_FLOAT, value]]
    if isinstance(value, str):
        return [_schema.VALUE_LITERAL, [_schema.LITERAL_STR, value]]
    # Complex Python value: wrap through LiteralVar so the JS string is
    # built by Reflex's own formatter, then treat as a Var.
    wrapped = _LITERAL_VAR.create(value)
    if isinstance(wrapped, _VAR):
        expr = wrapped._js_expr
        harvest.scan_expr(expr)
        return [_schema.VALUE_JS_EXPR, expr, _var_data_to_ir(wrapped, harvest)]
    return [_schema.VALUE_LITERAL, [_schema.LITERAL_STR, str(wrapped)]]


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
        return [_schema.COMPONENT_TEXT, "", 0, SYNTHETIC_LOC]
    if isinstance(contents, _VAR):
        expr = contents._js_expr
        harvest.scan_expr(expr)
        # JS string literal → text node; otherwise expression node.
        decoded = _decode_js_string(expr)
        if decoded is not None:
            return [_schema.COMPONENT_TEXT, decoded, 0, SYNTHETIC_LOC]
        return [
            _schema.COMPONENT_EXPR,
            [_schema.VALUE_JS_EXPR, expr, _var_data_to_ir(contents, harvest)],
            0,
            SYNTHETIC_LOC,
        ]
    return [_schema.COMPONENT_TEXT, str(contents), 0, SYNTHETIC_LOC]


def _decode_js_string(expr: str) -> str | None:
    if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
        try:
            import json

            return json.loads(expr)
        except ValueError:
            return None
    return None


def _children_to_ir(c: Any, harvest: _Harvest) -> list:
    children = getattr(c, "children", None) or ()
    return [_component_to_ir(ch, harvest) for ch in children]


def _fragment_to_ir(c: Any, harvest: _Harvest) -> list:
    return [_schema.COMPONENT_FRAGMENT, _children_to_ir(c, harvest), 0, SYNTHETIC_LOC]


def _cond_to_ir(c: Any, harvest: _Harvest) -> list:
    test = _value_to_ir(c.cond, harvest)
    children = list(c.children or ())
    then_ir = _component_to_ir(children[0], harvest) if children else None
    else_ir = _component_to_ir(children[1], harvest) if len(children) > 1 else None
    return [_schema.COMPONENT_COND, test, then_ir, else_ir, 0, SYNTHETIC_LOC]


def _foreach_to_ir(c: Any, harvest: _Harvest) -> list:
    # Phase-1 critical work: materialize body via _render() so the
    # iter-var arg has the correct type (ArrayCastedVar / ObjectVar).
    # Without this Rust would have to call _render() during phase 2.
    iter_tag = c._render()
    body_component = iter_tag.render_component()
    body_ir = _component_to_ir(body_component, harvest)
    iter_value = _value_to_ir(c.iterable, harvest)
    return [_schema.COMPONENT_FOREACH, iter_value, body_ir, 0, SYNTHETIC_LOC]


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
    return [_schema.COMPONENT_MATCH, test, arms, default, 0, SYNTHETIC_LOC]


def _element_to_ir(c: Any, harvest: _Harvest) -> list:
    cls = type(c)
    raw_tag = getattr(c, "tag", None)
    library = getattr(c, "library", None)
    alias = getattr(c, "alias", None)
    is_global = bool(getattr(c, "_is_tag_in_global_scope", False))

    # Tag resolution mirrors reflex_pyread::resolve_tag_symbol:
    # prefer alias, then tag; if library is None and the tag is in
    # global JS scope, quote it ("title", "meta") for jsx() emit.
    raw_name = alias or (raw_tag or "")
    if isinstance(raw_name, str):
        trimmed = raw_name.strip('"')
    else:
        trimmed = str(raw_name).strip('"')
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
    et = getattr(c, "event_triggers", None) or {}
    for trigger, handler in et.items():
        events.append(_event_to_ir(trigger, handler, harvest))
    hooks: list[list] = []  # phase-1 doesn't aggregate hooks per-element
    children = _children_to_ir(c, harvest)
    return [
        _schema.COMPONENT_ELEMENT,
        tag,
        props,
        children,
        events,
        hooks,
        0,
        SYNTHETIC_LOC,
    ]


# Dispatch table — class name → builder.
_DISPATCH = {
    "Bare": _bare_to_ir,
    "Fragment": _fragment_to_ir,
    "Cond": _cond_to_ir,
    "Foreach": _foreach_to_ir,
    "Match": _match_to_ir,
}


def _component_to_ir(c: Any, harvest: _Harvest) -> list:
    name = type(c).__name__
    fn = _DISPATCH.get(name, _element_to_ir)
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


def _merge_imports_into_harvest(raw: Any, harvest: _Harvest) -> None:
    """Fold a ``_get_all_imports()`` result into ``harvest.component_imports``.

    Mirrors ``import_alias_for``'s dotted-name handling and skips the
    React-runtime built-ins the Rust emitter declares itself.
    """
    if not raw:
        return
    for lib, ivs in raw.items():
        module = _FORMAT_LIB(lib) if lib else ""
        if not module:
            continue
        for iv in ivs:
            tag = getattr(iv, "tag", None) or ""
            alias = getattr(iv, "alias", None) or ""
            if not tag and not alias:
                continue
            tag_root = tag.split(".", 1)[0] if tag else ""
            alias_root = alias.split(".", 1)[0] if alias else ""
            if not tag_root and not alias_root:
                continue
            if module == "react" and tag_root in {
                "Fragment",
                "useContext",
                "useRef",
            }:
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
        _schema.SCHEMA_VERSION,
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
