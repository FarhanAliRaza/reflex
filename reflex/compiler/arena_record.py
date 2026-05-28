"""Native Python snapshot gatherer (refine-local plan, PR C).

Produces the snapshot **wire bundle** -- the same dict shape
``CompilerSession.dump_snapshot`` emits -- directly from a Component tree,
*without* the Rust freeze walk. The bundle is fed to
``CompilerSession.compile_page_from_arena(bundle, compute_close=True)``,
which rebuilds the ``Snapshot`` and runs the unchanged Rust memoize + emit
tail. Rust recomputes ``subtree_hash`` / ``PROPAGATES_HOOKS`` (the gatherer
cannot), so the bundle omits them.

The gatherer reads native attributes and reuses small existing Python
formatters (``ImportVar.name``, ``format_library_name``) rather than
re-rendering -- it mirrors the *input* side of ``freeze.rs``'s ``read_*``.

**Scope.** This first cut covers the structural / leaf surface:
``Element`` / ``Fragment`` / ``Bare`` with literal props, style, and
imports. Anything it cannot yet reproduce byte-identically -- reactive /
state vars, event handlers, hooks, control flow (Foreach/Cond/Match),
prop-embedded components, custom code, dynamic imports, refs, custom_attrs
-- raises :class:`GatherUnsupportedError` so the caller falls back to the
freeze path rather than emitting wrong output. Parity with the freeze walk
is asserted by ``test_arena_gather.py`` via the ``dump_snapshot`` oracle.
"""

from __future__ import annotations

from typing import Any

from reflex_base.components.component import Component
from reflex_base.utils.format import format_library_name, to_camel_case
from reflex_base.vars.base import LiteralVar, Var

# NodeKind discriminants (mirror reflex_ir::snapshot::kinds::NodeKind).
_KIND_ELEMENT = 0
_KIND_TEXT = 1
_KIND_FRAGMENT = 6

# NodeFlags bits (mirror reflex_ir::snapshot::flags::NodeFlags).
_FLAG_IS_BARE = 1 << 2
_FLAG_IS_SNAPSHOT_BOUNDARY = 1 << 3
_FLAG_TAG_IS_NONE = 1 << 8
_MEMO_DISP_SHIFT = 5


class GatherUnsupportedError(NotImplementedError):
    """Raised when the gatherer hits a Component shape it cannot yet
    reproduce byte-identically. The caller should fall back to the Rust
    freeze path for this page.
    """


def _qualname(component: object) -> str:
    """Return the originating Component class qualname."""
    return type(component).__qualname__


def _is_bare(component: object) -> bool:
    """Return whether ``component`` is a ``Bare`` text node."""
    return _qualname(component) == "Bare"


def _is_fragment(component: object) -> bool:
    """Return whether ``component`` is a ``Fragment``."""
    return _qualname(component) == "Fragment"


def _is_control_flow(component: object) -> bool:
    """Return whether ``component`` is a Foreach/Cond/Match node."""
    return _qualname(component) in ("Foreach", "Cond", "Match")


def _ensure_no_reactive(value: Any) -> None:
    """Raise if a Var carries reactive var-data.

    Reactive vars (state/hooks/imports) need the var_data side table, which
    this cut doesn't gather yet.

    Raises:
        GatherUnsupportedError: if ``value`` carries ``_var_data``.
    """
    if getattr(value, "_var_data", None) is not None:
        msg = f"reactive var-data on {value!r}"
        raise GatherUnsupportedError(msg)


def _render_value(value: Any) -> str:
    """Render a prop value to JS, mirroring freeze's ``render_value_as_js``.

    ``None`` renders to empty; a ``Var`` renders to its ``_js_expr``; any
    other literal is wrapped via ``LiteralVar.create`` (freeze's
    documented-equivalent fallback for the bool/int/float/str/mapping fast
    paths). Reactive var-data is out of scope for this cut.

    Args:
        value: the prop value (a Var or a plain literal).

    Returns:
        The JS expression string.
    """
    if value is None:
        return ""
    if isinstance(value, Var):
        _ensure_no_reactive(value)
        return str(value._js_expr)
    wrapped = LiteralVar.create(value)
    _ensure_no_reactive(wrapped)
    return str(wrapped._js_expr)


def _gather_imports(component: Component) -> list[tuple[str, str]]:
    """Gather import entries, mirroring ``read_imports_summary``.

    Normalizes each library name and formats each rendered ImportVar as
    ``tag as alias`` (``render=False`` entries are install-only and skipped).

    Args:
        component: the component to read imports from.

    Returns:
        A list of ``(module, binding)`` pairs.
    """
    out: list[tuple[str, str]] = []
    for lib, items in component._get_imports().items():
        if not lib:
            continue
        module = format_library_name(lib)
        if not module:
            continue
        for iv in items:
            if getattr(iv, "render", True) is False:
                continue
            name = iv.name  # ImportVar.name == "tag as alias" / alias / "*"
            if name:
                out.append((module, name))
    return out


def _gather_style(component: Component) -> str:
    """Gather the style JS object literal, mirroring freeze's ``read_style``.

    Args:
        component: the component to read style from.

    Returns:
        The ``css`` entry of ``_get_style()`` rendered to its ``_js_expr``,
        or empty string when there is no style.
    """
    css = component._get_style().get("css")
    if css is None:
        return ""
    _ensure_no_reactive(css)
    expr = str(getattr(css, "_js_expr", ""))
    if expr in ("", "({  })", "({})"):
        return ""
    return expr


def _camelize_prop_name(name: str) -> str:
    """Camelize a prop name, mirroring freeze's ``camelize_prop_name``.

    Uses ``to_camel_case`` with hyphens left intact (``access_key`` ->
    ``accessKey``, ``class_name`` -> ``className``).

    Args:
        name: the snake_case prop name.

    Returns:
        The camelCase prop name.
    """
    return to_camel_case(name, treat_hyphens_as_underscores=False)


def _gather_rendered_props(component: Component) -> list[tuple[str, str]]:
    """Gather rendered props, mirroring ``read_rendered_props``.

    Dataclass props (trailing ``_`` stripped, ``None`` skipped, name
    camelized) then identity props (key/id/class_name). custom_attrs are out
    of scope.

    Args:
        component: the component to read props from.

    Returns:
        A list of ``(camelCase_name, js_expr)`` pairs.

    Raises:
        GatherUnsupportedError: if the component sets ``custom_attrs``.
    """
    if getattr(component, "custom_attrs", None):
        msg = "custom_attrs not yet gathered"
        raise GatherUnsupportedError(msg)

    pairs: list[tuple[str, str]] = []
    for raw in component.get_props():
        attr = raw.removesuffix("_")
        value = getattr(component, raw, None)
        if value is None:
            continue
        expr = _render_value(value)
        if not expr:
            continue
        pairs.append((_camelize_prop_name(attr), expr))
    for name in ("key", "id", "class_name"):
        value = getattr(component, name, None)
        if value is None:
            continue
        expr = _render_value(value)
        if expr:
            pairs.append((_camelize_prop_name(name), expr))
    return pairs


def _gather_rename_props(component: Component) -> list[tuple[str, str]]:
    """Gather the class rename-props map, mirroring ``read_rename_props``.

    Args:
        component: the component to read ``_rename_props`` from.

    Returns:
        ``(old, new)`` pairs (already camelCase keyed); empty if none.
    """
    rename = getattr(component, "_rename_props", None)
    if not rename:
        return []
    return [(str(k), str(v)) for k, v in rename.items()]


def _memo_flags(component: Component) -> int:
    """Compute the memoization-mode flag bits, mirroring freeze.

    Sets ``IS_SNAPSHOT_BOUNDARY`` when ``_memoization_mode.recursive`` is
    ``False``, plus the disposition bits (``never`` -> 1, ``always`` -> 2,
    else Auto/0) in bits 5-6.

    Args:
        component: the component to read ``_memoization_mode`` from.

    Returns:
        The memoization flag bits.
    """
    mode = getattr(component, "_memoization_mode", None)
    if mode is None:
        return 0
    flags = 0
    if not getattr(mode, "recursive", True):
        flags |= _FLAG_IS_SNAPSHOT_BOUNDARY
    disp = getattr(getattr(mode, "disposition", None), "value", None)
    if disp == "never":
        flags |= 1 << _MEMO_DISP_SHIFT
    elif disp == "always":
        flags |= 2 << _MEMO_DISP_SHIFT
    return flags


def _reject_unsupported(component: Component) -> None:
    """Refuse the per-node surface this cut doesn't reproduce yet.

    Raises:
        GatherUnsupportedError: for event triggers, hooks, custom code,
            dynamic imports, or prop-embedded components.
    """
    if getattr(component, "event_triggers", None):
        msg = "event triggers not yet gathered"
        raise GatherUnsupportedError(msg)
    if component._get_hooks_internal() or component._get_hooks():
        msg = "hooks not yet gathered"
        raise GatherUnsupportedError(msg)
    if component._get_custom_code():
        msg = "custom code not yet gathered"
        raise GatherUnsupportedError(msg)
    if component._get_dynamic_imports():
        msg = "dynamic imports not yet gathered"
        raise GatherUnsupportedError(msg)
    if component._get_components_in_props():
        msg = "components-in-props not yet gathered"
        raise GatherUnsupportedError(msg)


def _bare_text_value(component: Component) -> str:
    """Return the literal text content of a Bare node.

    JS-string-escaped with no surrounding quotes, mirroring freeze's
    ``text_value`` side-table entry.

    Args:
        component: the Bare component.

    Returns:
        The escaped text content.

    Raises:
        GatherUnsupportedError: if the Bare contents are not a literal string.
    """
    contents = getattr(component, "contents", None)
    _ensure_no_reactive(contents)
    expr = str(getattr(contents, "_js_expr", ""))
    if len(expr) >= 2 and expr[0] == '"' and expr[-1] == '"':
        return expr[1:-1]
    msg = f"non-literal Bare contents {contents!r}"
    raise GatherUnsupportedError(msg)


def _empty_node() -> dict:
    """Return a node dict pre-populated with every wire field at its default.

    Returns:
        A fresh node dict.
    """
    return {
        "kind": _KIND_ELEMENT,
        "tag": "",
        "style_key": "",
        "style": "",
        "rendered_props": [],
        "event_callbacks": [],
        "imports": [],
        "hooks_internal": [],
        "hooks_user": [],
        "custom_code": "",
        "dynamic_imports": [],
        "ref_name": "",
        "vars_used": [],
        "children": (0, 0),
        "flags": 0,
    }


class Gatherer:
    """Builds the flat node list with freeze's layout.

    Direct children occupy a contiguous block (reserved before recursion);
    each child's subtree is filled depth-first afterward.
    """

    def __init__(self) -> None:
        """Initialize an empty node arena."""
        self.nodes: list[dict | None] = []

    def _reserve(self) -> int:
        idx = len(self.nodes)
        self.nodes.append(None)
        return idx

    def _child_components(self, component: Component) -> list[Component]:
        if _is_control_flow(component):
            msg = f"control flow {_qualname(component)}"
            raise GatherUnsupportedError(msg)
        return [c for c in component.children if isinstance(c, Component)]

    def _fill(self, component: Component, idx: int) -> None:
        if _is_bare(component):
            node = self._gather_leaf_bare(component)
            node["children"] = (len(self.nodes), len(self.nodes))
            self.nodes[idx] = node
            return

        children = self._child_components(component)
        start = len(self.nodes)
        child_idxs = [self._reserve() for _ in children]
        end = len(self.nodes)

        node = self._gather_element(component)
        node["children"] = (start, end)
        self.nodes[idx] = node

        for child, cidx in zip(children, child_idxs, strict=True):
            self._fill(child, cidx)

    def _gather_element(self, component: Component) -> dict:
        _reject_unsupported(component)
        node = _empty_node()
        is_fragment = _is_fragment(component)
        tag = (
            None
            if is_fragment
            else (getattr(component, "alias", None) or getattr(component, "tag", None))
        )
        node["tag"] = str(tag) if tag else ""
        node["kind"] = _KIND_FRAGMENT if is_fragment else _KIND_ELEMENT
        node["style_key"] = _qualname(component)
        node["style"] = "" if is_fragment else _gather_style(component)
        node["rendered_props"] = (
            [] if is_fragment else _gather_rendered_props(component)
        )
        node["imports"] = _gather_imports(component)
        flags = _memo_flags(component)
        if not node["tag"]:
            flags |= _FLAG_TAG_IS_NONE
        node["flags"] = flags
        node["_rename"] = _gather_rename_props(component)
        return node

    def _gather_leaf_bare(self, component: Component) -> dict:
        node = _empty_node()
        node["kind"] = _KIND_TEXT
        node["style_key"] = "Bare"
        node["flags"] = _FLAG_IS_BARE | _FLAG_TAG_IS_NONE | _memo_flags(component)
        node["imports"] = _gather_imports(component)
        node["_text_value"] = _bare_text_value(component)
        return node


def gather_arena(root: Component) -> dict:
    """Gather a styled Component tree into a snapshot wire bundle.

    The result matches ``dump_snapshot(root)`` for the supported subset,
    except for the Rust-computed ``subtree_hash`` / ``PROPAGATES_HOOKS``
    fields (recomputed by ``compile_page_from_arena(..., compute_close=True)``).

    Args:
        root: a fully styled root Component (post ``_add_style_recursive``).

    Returns:
        The wire bundle dict.

    Raises:
        GatherUnsupportedError: if any node uses a feature this cut can't yet
            reproduce byte-identically.
    """
    g = Gatherer()
    root_idx = g._reserve()
    g._fill(root, root_idx)

    nodes: list[dict] = []
    control_flow_text: dict[int, str] = {}
    rename_props: dict[int, list[tuple[str, str]]] = {}
    for i, node in enumerate(g.nodes):
        assert node is not None
        text_value = node.pop("_text_value", None)
        if text_value is not None:
            control_flow_text[i] = text_value
        rename = node.pop("_rename", None)
        if rename:
            rename_props[i] = rename
        nodes.append(node)

    return {
        "root": root_idx,
        "nodes": nodes,
        "var_data": [],
        "var_hooks": [],
        "var_imports": [],
        "var_deps": [],
        "var_components": [],
        "control_flow": {
            "text_value": control_flow_text,
            "cond_test": {},
            "foreach_iter": {},
            "match_value": {},
            "expr_value": {},
            "memo_key": {},
            "match_arms": {},
            "match_default": {},
        },
        "wrap_redirects": {},
        "app_wraps": [],
        "add_custom_code_extra": {},
        "special_props": {},
        "rename_props": rename_props,
        "app_style_map": {},
        "page_meta": {
            "schema_version": 0,
            "route": "",
            "title": "",
            "meta": [],
        },
    }
