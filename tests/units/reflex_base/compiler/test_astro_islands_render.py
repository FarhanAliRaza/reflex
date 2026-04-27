"""Unit tests for the islands-mode static HTML renderer.

Covers ``packages/reflex-base/src/reflex_base/compiler/astro_islands_render.py``.
"""

from __future__ import annotations

from reflex_base.compiler.astro_islands_render import (
    IslandsRenderResult,
    _emit_island_module,
    _is_html_tag_name,
    _island_target_from_component,
    _looks_like_state_expression,
    _render_node,
    _render_props_as_attrs,
    _render_props_as_jsx_attrs,
    _strip_quotes,
    render_islands_page,
)
from reflex_components_core.base.bare import Bare


def test_strip_quotes_handles_quoted_literal():
    assert _strip_quotes('"div"') == "div"


def test_strip_quotes_returns_raw_for_identifier():
    assert _strip_quotes("MyComponent") == "MyComponent"


def test_is_html_tag_name_lowercase():
    assert _is_html_tag_name("div") is True
    assert _is_html_tag_name("button") is True
    assert _is_html_tag_name("MyComponent") is False
    assert _is_html_tag_name("Fragment") is False
    assert _is_html_tag_name("Bare_comp_xyz") is False


def test_looks_like_state_expression_detects_reflex_runtime_paths():
    assert _looks_like_state_expression("reflex___state____state.foo_rx_state_") is True
    assert _looks_like_state_expression("addEvents([1, 2])") is True
    assert _looks_like_state_expression("hello world") is False


def test_render_props_as_attrs_keeps_string_literals():
    props = ['className:"foo"', 'id:"bar"']
    out = _render_props_as_attrs(props)
    assert ' class="foo"' in out
    assert ' id="bar"' in out


def test_render_props_as_attrs_drops_callbacks_and_dynamic_vars():
    props = [
        "onClick:((_e) => addEvents([...]))",
        "value:reflex___state____state.x",
    ]
    out = _render_props_as_attrs(props)
    assert "onClick" not in out
    assert "value" not in out


def test_render_props_as_attrs_unquotes_hyphenated_keys():
    """``format_props`` quotes ``data-*`` / ``aria-*`` keys for JSX; the HTML
    renderer must strip those quotes so the attribute name is bare.

    Without this, ``data-accent-color="blue"`` ends up as
    ``"data-accent-color"="blue"`` in the static HTML and the Radix
    ``tokens.css`` selectors never match.
    """
    props = ['"data-accent-color":"blue"', '"aria-label":"Close"']
    out = _render_props_as_attrs(props)
    assert ' data-accent-color="blue"' in out
    assert ' aria-label="Close"' in out
    assert '"data-accent-color"' not in out


def test_render_node_emits_html_for_static_tree():
    rendered = {
        "name": '"div"',
        "props": [],
        "children": [
            {"name": '"h1"', "props": [], "children": [{"contents": '"Hello"'}]},
            {"name": '"p"', "props": [], "children": [{"contents": '"World"'}]},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<div>" in body
    assert "<h1>" in body
    assert "Hello" in body
    assert "World" in body
    assert "</div>" in body


def test_render_node_emits_island_placeholder():
    rendered = {
        "name": '"div"',
        "props": [],
        "children": [
            {"_island_placeholder": ("MyIsland", "client:only", None)},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert '<MyIsland client:only="react" />' in body


def test_render_node_emits_island_with_directive():
    rendered = {
        "name": '"div"',
        "props": [],
        "children": [
            {"_island_placeholder": ("MyIsland", "client:visible", None)},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<MyIsland client:visible />" in body


def test_render_node_emits_ssr_only_without_client_directive():
    """SSR-only placements emit a bare ``<Component />`` tag, no ``client:*``.

    Astro renders the React component server-side and ships zero JS for
    it. Auto-memo wrappers around stateless components (e.g. icon-only
    wrappers) take this path so they don't pay per-island hydration
    overhead.
    """
    rendered = {
        "name": '"div"',
        "props": [],
        "children": [
            {"_island_placeholder": ("MyMemo", None, None)},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<MyMemo />" in body
    assert "client:" not in body


def test_render_node_ssr_only_forwards_props():
    """SSR-only tags carry static props through to the SSR pass.

    Without prop forwarding, e.g. an icon memo would render with the
    component's defaults instead of the per-call icon name / size.
    """
    rendered = {
        "_island_placeholder": ("IconMemo", None, None),
        "_island_props": [
            "size:16",
            "strokeWidth:1.5",
            'className:"text-current"',
        ],
        "children": [],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<IconMemo" in body
    assert "client:" not in body
    assert " size={16}" in body
    assert " strokeWidth={1.5}" in body
    assert ' className="text-current"' in body
    # Self-closes since there are no children.
    assert " />" in body


def test_render_node_ssr_only_with_children_renders_open_close_pair():
    """SSR-only wrappers with children produce a real open/close tag.

    Auto-memo passthrough wrappers like ``Section_section_<hash>`` accept
    children via the memo's ``{children}`` slot — self-closing the tag
    would render an empty shell server-side.
    """
    rendered = {
        "_island_placeholder": ("WrapperMemo", None, None),
        "_island_props": [],
        "children": [
            {"name": '"h1"', "props": [], "children": [{"contents": '"Hi"'}]},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<WrapperMemo>" in body
    assert "</WrapperMemo>" in body
    assert "<h1>" in body
    assert "Hi" in body
    assert "client:" not in body


def test_render_props_as_jsx_attrs_preserves_static_props():
    """Static-string, boolean, and numeric props all survive the JSX transform.

    Without this, an island like ``GradientButton variant="ghost" size="xs"``
    SSRs as ``<GradientButton client:visible />`` and falls back to the
    component's defaults — every island looks like a default-variant button.
    """
    props = [
        'variant:"ghost"',
        'size:"xs"',
        'className:"font-[525] w-full"',
        "nativeButton:true",
        "tabIndex:-1",
        "onClick:((_e) => addEvents([...]))",
    ]
    out = _render_props_as_jsx_attrs(props)
    assert ' variant="ghost"' in out
    assert ' size="xs"' in out
    # className stays in JSX form (not lower-cased like HTML's `class`).
    assert ' className="font-[525] w-full"' in out
    # Booleans and numerics need {} so JSX doesn't coerce them to strings.
    assert " nativeButton={true}" in out
    assert " tabIndex={-1}" in out
    # Event callbacks can't be serialized; they must be dropped.
    assert "onClick" not in out


def test_render_node_island_forwards_static_props():
    """Island tags carry the component's variant/size/className from the source.

    Regression: previously every island emitted as
    ``<Island client:visible />`` with no other attributes, so non-default
    variants (ghost buttons, xs sizes) all rendered as the primary/md default.
    """
    rendered = {
        "_island_placeholder": ("GradientButton", "client:visible", None),
        "_island_props": [
            'variant:"ghost"',
            'size:"xs"',
            'className:"font-[525]"',
        ],
        "children": [{"contents": '"Click me"'}],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<GradientButton client:visible" in body
    assert ' variant="ghost"' in body
    assert ' size="xs"' in body
    assert ' className="font-[525]"' in body
    assert "Click me" in body


def test_render_node_emits_island_with_nested_children():
    """Islands with children render an open/close pair so the slot has content.

    Auto-memo wrappers like ``Section_section_<hash>`` are
    ``memo(({children}) => jsx("section", {...}, children))`` — they
    expect children to be passed in. Self-closing the tag would render
    an empty shell at SSR time. Passing the rendered subtree as Astro
    slot content produces real HTML.
    """
    rendered = {
        "_island_placeholder": ("HeroSection", "client:visible", None),
        "children": [
            {"name": '"h1"', "props": [], "children": [{"contents": '"Hello"'}]},
            {"_island_placeholder": ("InnerIsland", "client:visible", None)},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<HeroSection client:visible>" in body
    assert "</HeroSection>" in body
    assert "<h1>" in body
    assert "Hello" in body
    # Nested islands round-trip through their own self-close path when
    # they have no further children.
    assert "<InnerIsland client:visible />" in body


def test_render_node_drops_state_expressions_safely():
    rendered = {"contents": "reflex___state____state.counter_rx_state_"}
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "<!-- reflex islands: dropped state expression -->" in body


def test_render_node_unknown_component_emits_comment():
    rendered = {
        "name": "MysteryComponent",
        "props": [],
        "children": [],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    assert "unrendered component MysteryComponent" in body


def test_emit_island_module_is_clean_re_export():
    """Per-island module is a single-line re-export from the source library.

    The shared runtime is SSR-safe (router adapter has sane server-side
    defaults; React Contexts default to empty values), so the island
    module is just ``export { Tag as default } from "<library>"``.
    Astro's ``client:visible`` directive on the .astro page handles the
    deferral.
    """
    artifact = _emit_island_module(
        route="/",
        island_name="MyIsland",
        export_name="WrapperX",
        import_source="$/utils/components/WrapperX",
    )
    assert artifact.path == "src/reflex/islands/index/MyIsland.tsx"
    assert (
        'export { WrapperX as default } from "$/utils/components/WrapperX";'
        in artifact.contents
    )
    # No defensive lazy/Suspense scaffolding — the runtime SSRs cleanly now.
    assert "lazy" not in artifact.contents
    assert "Suspense" not in artifact.contents


def test_emit_island_module_preserves_import_source_verbatim():
    """``import_source`` is taken verbatim — no path math regardless of route depth."""
    a = _emit_island_module(
        route="/",
        island_name="X",
        export_name="W",
        import_source="$/utils/components/W",
    )
    assert 'from "$/utils/components/W"' in a.contents
    assert "../" not in a.contents

    deep = _emit_island_module(
        route="/a/b/c",
        island_name="Z",
        export_name="W",
        import_source="$/utils/components/W",
    )
    assert deep.path == "src/reflex/islands/a/b/c/Z.tsx"
    assert 'from "$/utils/components/W"' in deep.contents
    # The same source string survives unchanged regardless of depth — the
    # `$/` Vite alias resolves from any directory.
    assert "../" not in deep.contents


def test_emit_island_module_handles_non_utils_libraries():
    """Custom user libraries (e.g. ``$/public/components/...``) flow through unchanged."""
    artifact = _emit_island_module(
        route="/",
        island_name="GradientButton",
        export_name="GradientButton",
        import_source="$/public/components/GradientButton",
    )
    assert (
        'export { GradientButton as default } from "$/public/components/GradientButton";'
        in artifact.contents
    )


def test_island_target_recognizes_experimental_memo():
    """Auto-memo wrappers expose ``(tag, library)``."""
    from reflex.experimental.memo import _get_experimental_memo_component_class

    cls = _get_experimental_memo_component_class("Bare_comp_xyz")
    instance = cls.__new__(cls)
    object.__setattr__(instance, "tag", "Bare_comp_xyz")
    object.__setattr__(instance, "library", "$/utils/components/Bare_comp_xyz")
    assert _island_target_from_component(instance) == (
        "Bare_comp_xyz",
        "$/utils/components/Bare_comp_xyz",
    )


def test_island_target_recognizes_custom_component():
    """``@rx.memo`` (CustomComponent) is treated as an island. Its
    ``library`` is per-file (``$/utils/components/<tag>``) so the per-island
    re-export does not pull the whole components barrel into the chunk.
    """
    from reflex_base.components.component import CustomComponent

    instance = CustomComponent.__new__(CustomComponent)
    object.__setattr__(instance, "tag", "DocsNavbar")
    object.__setattr__(instance, "library", "$/utils/components/DocsNavbar")
    assert _island_target_from_component(instance) == (
        "DocsNavbar",
        "$/utils/components/DocsNavbar",
    )


def test_island_target_recognizes_plain_component_with_local_library():
    """User-authored ``rx.Component`` subclasses with local libraries qualify."""

    class _Stub:
        tag = "GradientButton"
        library = "$/public/components/GradientButton"

    assert _island_target_from_component(_Stub()) == (
        "GradientButton",
        "$/public/components/GradientButton",
    )


def test_island_target_skips_html_elements():
    """HTML element render dicts and primitives never become islands."""

    class _Div:
        tag = "div"
        library = "$/utils/components"

    class _Frag:
        tag = "Fragment"
        library = "$/utils/components"

    assert _island_target_from_component(_Div()) is None
    assert _island_target_from_component(_Frag()) is None
    assert _island_target_from_component(None) is None


def test_island_target_rejects_third_party_libraries():
    """A bare NPM library (e.g. ``@radix-ui/themes``) is not safely re-exportable.

    Re-exporting a third-party React symbol verbatim would produce an
    island whose default export is the bare third-party component — not
    a Reflex-compiled wrapper. Such components must opt in via
    ``provides_hydrated_context = True`` so an enclosing island wraps
    them instead.
    """

    class _Radix:
        tag = "Theme"
        library = "@radix-ui/themes"

    class _NoLibrary:
        tag = "Foo"
        library = ""

    assert _island_target_from_component(_Radix()) is None
    assert _island_target_from_component(_NoLibrary()) is None


def test_render_node_drops_null_and_undefined_text():
    """`cond(... else None)` renders as the bare JS literal ``null`` —
    drop it instead of emitting ``null`` as visible page text.
    """
    rendered = {
        "name": '"div"',
        "props": [],
        "children": [
            "null",
            "undefined",
            {"contents": "null"},
            {"name": '"span"', "props": [], "children": [{"contents": '"keep me"'}]},
        ],
    }
    out: list[str] = []
    _render_node(rendered, island_lookup={}, indent="", out=out)
    body = "\n".join(out)
    # The bare 'null'/'undefined' children are dropped; the real span survives.
    assert "null" not in body
    assert "undefined" not in body
    assert "keep me" in body


def test_render_islands_page_static_only_returns_inline_html():
    """A page tree with no auto-memo wrappers produces only static HTML."""
    root = Bare.create("hello world")
    result = render_islands_page(route="/", root=root)
    assert isinstance(result, IslandsRenderResult)
    assert result.island_modules == ()
    assert result.imports == ()
    assert result.directives == ()
    # The renderer outputs inline HTML for the static contents.
    assert "hello world" in result.body


def test_render_islands_page_ssr_only_memo_emits_no_client_directive():
    """A stateless auto-memo wrapper compiles to an SSR-only Astro tag.

    End-to-end: ``render_islands_page`` runs the classifier, picks up the
    SSR-only verdict, generates the per-route island module, and emits
    the JSX tag without a ``client:*`` attribute. Astro renders the
    component server-side and ships zero JS for it.
    """
    from reflex_base.components.component import Component, field
    from reflex_base.vars.base import LiteralVar, Var

    from reflex.experimental.memo import create_passthrough_component_memo

    class _Plain(Component):
        tag = "Plain"
        library = "plain-lib"
        label: Var[str] = field(default=LiteralVar.create(""))

    inner = _Plain.create()
    wrapper_factory, _ = create_passthrough_component_memo("MyMemo", inner)
    wrapper = wrapper_factory()
    object.__setattr__(wrapper, "_memoized_source", inner)

    result = render_islands_page(route="/", root=wrapper)
    # One per-route island module is still emitted so the .astro can
    # import the wrapper for SSR.
    assert len(result.island_modules) == 1
    assert len(result.imports) == 1
    # Directive is None because no JS is shipped for the component.
    assert result.directives == (None,)
    # The body emits the JSX tag without a client directive.
    assert "<MyMemo" in result.body
    assert "client:" not in result.body
