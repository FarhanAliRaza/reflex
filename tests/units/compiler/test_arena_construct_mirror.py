"""M3 phase-1 gate: the arena construction fast path is byte-identical.

Inside ``arena_construction()`` (set by the Rust pipeline under
``REFLEX_ARENA_CONSTRUCT=1``), eligible ``Component.create`` calls skip
``_post_init`` and mirror kwargs into the instance ``__dict__`` — Var-typed
props ``LiteralVar``-wrapped exactly as ``_post_init`` does. Each fixture
compiles the same page with the scope off and on; page JS, memo bodies, and
imports must match byte-for-byte. Calls the mirror can't reproduce (event
triggers, style inputs, special attrs, non-str class_name) must fall back
to ``_post_init`` and still match trivially.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from reflex_base.components.component import Component, arena_construction
from reflex_base.vars.base import Var, VarData

import reflex as rx
from reflex.app import UnevaluatedPage
from reflex.compiler.compiler import compile_unevaluated_page
from reflex.compiler.session import CompilerSession

pytest.importorskip("reflex_compiler_rust._native")

_IMPORT_FIELDS = ("tag", "alias", "is_default", "install", "render", "package_path")


def _canon_imports(imports: dict) -> dict[str, list[str]]:
    return {
        lib: sorted({
            repr(tuple(getattr(iv, f, None) for f in _IMPORT_FIELDS)) for iv in ivs
        })
        for lib, ivs in sorted(imports.items())
    }


def _compile(build: Callable[[], Component], *, arena: bool) -> tuple[str, list, dict]:
    sess = CompilerSession()
    unev = UnevaluatedPage(component=build, route="/arena-mirror-diff")
    with arena_construction(arena):
        component = compile_unevaluated_page(
            "/arena-mirror-diff", unev, {}, None, apply_style=False
        )
    page_js, bodies, imports, _ = sess.compile_page_from_component_arena(
        component, "ArenaMirrorDiff", "arena-mirror-diff", app_style={}
    )
    return page_js, sorted(bodies), _canon_imports(imports)


def _assert_arena_parity(build: Callable[[], Component]) -> str:
    rich_js, rich_bodies, rich_imports = _compile(build, arena=False)
    arena_js, arena_bodies, arena_imports = _compile(build, arena=True)
    assert arena_js == rich_js
    assert arena_bodies == rich_bodies
    assert arena_imports == rich_imports
    # Content assertions search the page plus memo bodies (stateful or
    # event-bearing subtrees get memoized out of the page function).
    return rich_js + "\n".join(jsx for _, jsx in rich_bodies)


_STATE_VAR = Var(
    "stateValue",
    _var_data=VarData(hooks={"const stateValue = 1;": None}),
).to(str)


def test_literal_var_props_mirror():
    js = _assert_arena_parity(
        lambda: rx.box(
            rx.text("hello", size="3"),
            rx.heading("head", as_="h2"),
            rx.spacer(),
        )
    )
    assert "hello" in js


def test_state_var_props_mirror():
    js = _assert_arena_parity(
        lambda: rx.box(rx.input(value=_STATE_VAR, placeholder="type"))
    )
    assert "stateValue" in js


def test_event_triggers_mirror():
    js = _assert_arena_parity(
        lambda: rx.box(
            rx.button("click", on_click=rx.console_log("x")),
            rx.input(value=_STATE_VAR, on_change=rx.console_log("c")),
            rx.box(on_mount=rx.console_log("m"), on_unmount=rx.console_log("u")),
        )
    )
    assert "console" in js


def test_style_inputs_mirror():
    from reflex_base.breakpoints import Breakpoints

    _assert_arena_parity(
        lambda: rx.box(
            rx.text("styled", style={"color": "red"}),
            rx.text("shorthand", background_color="blue"),
            rx.text("both", style={"color": "red"}, margin="2px"),
            rx.text("listy", style=[{"color": "red"}, {"padding": "1px"}]),
            rx.text("bp", style=Breakpoints(initial={"color": "red"})),
            rx.text("varstyle", style=Var("dynSty").to(dict)),
            rx.text("pseudo", _hover={"color": "green"}),
        )
    )


def test_style_string_raises_on_both_paths():
    def build():
        return rx.box(rx.text("bad", style="nope"))  # pyright: ignore[reportArgumentType]

    with pytest.raises(TypeError, match="Style must be"):
        _compile(build, arena=False)
    with pytest.raises(TypeError, match="Style must be"):
        _compile(build, arena=True)


def test_special_attrs_mirror():
    js = _assert_arena_parity(
        lambda: rx.box(
            rx.text("t", data_testid="x", aria_label="lbl"),
            rx.text("merge", data_foo="1", custom_attrs={"spellcheck": "false"}),
        )
    )
    assert "data-testid" in js
    assert "aria-label" in js


def test_event_lambda_values_delegate():
    # Callable values delegate to EventChain.create (full path) — parity.
    js = _assert_arena_parity(
        lambda: rx.box(rx.button("l", on_click=lambda: rx.console_log("lam")))
    )
    assert "lam" in js


def test_parsed_args_spec_cache_shares_per_spec():
    from reflex_base.event import _parse_args_spec_cached, no_args_event_spec

    first = _parse_args_spec_cached(no_args_event_spec)
    assert _parse_args_spec_cached(no_args_event_spec) is first

    def other_spec(value: Var[str]) -> tuple[Var[str]]:
        return (value,)

    other = _parse_args_spec_cached(other_spec)
    assert other is not first
    assert len(other) == 1
    assert _parse_args_spec_cached(other_spec) is other


def test_event_signature_validation_skipped_under_arena():
    from reflex_base.event import EventHandler
    from reflex_base.utils.exceptions import EventFnArgMismatchError

    def needs_three(a, b, c):
        return None

    handler = EventHandler(fn=needs_three)
    with pytest.raises(EventFnArgMismatchError):
        rx.button("b", on_click=handler)
    # Documented difference: the arena fast path skips
    # check_fn_match_arg_spec / arg-type subclass validation.
    with arena_construction():
        comp = rx.button("b", on_click=handler)
    assert comp is not None


def test_event_triggers_kwarg_dict_mirrors():
    from reflex_base.event import EventChain, no_args_event_spec

    chain = EventChain.create(
        value=rx.console_log("pre"), args_spec=no_args_event_spec, key="on_click"
    )
    _assert_arena_parity(
        lambda: rx.box(rx.button("b", event_triggers={"on_click": chain}))
    )


def test_class_name_variants():
    _assert_arena_parity(
        lambda: rx.box(
            rx.text("plain", class_name="a b"),
            rx.text("listy", class_name=["a", "b"]),
            rx.text("varname", class_name=Var("dynCls").to(str)),
        )
    )


def test_raw_fields_mirror():
    _assert_arena_parity(
        lambda: rx.box(
            rx.text("k", key="some-key", id="an-id"),
            rx.el.div("attrs", custom_attrs={"spellcheck": "false"}),
        )
    )


def test_create_override_mutation_sites():
    # Form patches handle_submit_unique_name post-create; DebounceInput
    # swaps methods on its child. Both operate on the mirror instance dict.
    _assert_arena_parity(
        lambda: rx.box(
            rx.form(rx.input(value=_STATE_VAR), on_submit=rx.console_log("s")),
            rx.debounce_input(
                rx.input(value=_STATE_VAR, on_change=rx.console_log("c"))
            ),
        )
    )


def test_upload_special_props_mutation_normalized():
    import re

    # Upload generates random unique variable names per EVALUATION (its
    # rich-vs-rich A/A already differs), so this fixture compares modulo
    # those tokens. It pins the special_props post-create append working
    # against the mirror instance dict.
    def norm(text: str) -> str:
        text = re.sub(r"_memo_[0-9a-f]{16}", "_memo_X", text)
        text = re.sub(r'key: "\d+"', 'key: "K"', text)
        text = re.sub(r"_[0-9a-f]{32}", "_H", text)
        return re.sub(r"\b[a-z]{8}\b", "ident", text)

    build = lambda: rx.box(rx.upload(rx.text("up")))  # noqa: E731
    rich_js, rich_bodies, _ = _compile(build, arena=False)
    arena_js, arena_bodies, _ = _compile(build, arena=True)
    assert norm(arena_js) == norm(rich_js)
    assert sorted(norm(j) for _, j in arena_bodies) == sorted(
        norm(j) for _, j in rich_bodies
    )
    assert "getRootProps" in arena_js + "".join(j for _, j in arena_bodies)


def test_control_flow_create_callers():
    _assert_arena_parity(
        lambda: rx.box(
            rx.foreach(Var.create(["a", "b"]), lambda item: rx.text(item)),
            rx.cond(_STATE_VAR.bool(), rx.text("yes"), rx.text("no")),
            rx.match(_STATE_VAR, ("a", rx.text("A")), rx.text("default")),
        )
    )


def test_markdown_mirrors():
    _assert_arena_parity(lambda: rx.box(rx.markdown("**bold** and `code`")))


def test_add_style_class_with_fold():
    class FoldedComp(Component):
        tag = "FoldedComp"
        library = "arena-mirror-lib"

        def add_style(self):
            """Class default style for the fold.

            Returns:
                The default style dict.
            """
            return {"color": "rebeccapurple"}

    js = _assert_arena_parity(lambda: rx.box(FoldedComp.create(prop_a="x")))
    assert "rebeccapurple" in js


def test_custom_post_init_class_never_fast_paths():
    calls = []

    class CustomInit(Component):
        tag = "CustomInit"
        library = "arena-mirror-lib"
        val: Var[str]

        def _post_init(self, *args, **kwargs):
            """Track invocations, then defer to the base constructor.

            Args:
                *args: positional args for the base constructor.
                **kwargs: keyword args for the base constructor.
            """
            calls.append(1)
            super()._post_init(*args, **kwargs)

    assert not CustomInit._arena_create_eligible()
    _assert_arena_parity(lambda: rx.box(CustomInit.create(val="v")))
    assert calls  # _post_init ran on both compiles


def test_fast_path_skips_post_init(monkeypatch):
    seen = []
    real = Component._post_init

    def spy(self, *args, **kwargs):
        seen.append(type(self).__name__)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Component, "_post_init", spy)
    with arena_construction():
        rx.text("fast", size="3")
        rx.text("evt", on_click=rx.console_log("x"))
        rx.text("sty", style={"color": "red"}, background_color="blue")
        rx.text("attrs", data_testid="t")
    assert "Text" not in seen
    seen.clear()
    rx.text("slow", size="3")
    assert "Text" in seen
    seen.clear()
    with arena_construction(False):
        rx.text("slow2", size="3")
    assert "Text" in seen


def test_validation_skipped_under_arena():
    # Documented behavior difference behind the flag: satisfies_type_hint
    # does not run on the fast path.
    with pytest.raises(TypeError):
        # trim expects a literal union, not int
        rx.text("x", trim=42)  # pyright: ignore[reportArgumentType]
    with arena_construction():
        comp = rx.text("x", trim=42)  # pyright: ignore[reportArgumentType]
    assert comp is not None


def test_construction_stages_vars_cache():
    with arena_construction():
        comp = rx.input(value=_STATE_VAR)
    staged = comp.__dict__.get("_vars_cache")
    assert staged is not None
    # rx.input's create() wraps the value in a null-guard ternary, so the
    # staged var's expression embeds the state var.
    assert any(_STATE_VAR._js_expr in v._js_expr for v in staged)
    # css-shorthand vars ride the synthetic style var.
    with arena_construction():
        styled = rx.text("hi", color=_STATE_VAR)
    assert any(v._js_expr == "style" for v in styled.__dict__["_vars_cache"])


def test_non_harvest_writes_keep_staged_vars():
    with arena_construction():
        comp = rx.input(value=_STATE_VAR)  # radix create() patches alias
    assert "_vars_cache" in comp.__dict__
    comp.alias = "Renamed"
    assert "_vars_cache" in comp.__dict__


def test_setattr_invalidates_staged_vars():
    with arena_construction():
        comp = rx.input(value=_STATE_VAR)
    assert "_vars_cache" in comp.__dict__
    # The audited mutation shape (Upload-style field assignment) must drop
    # the staged harvest; the next read recomputes from live fields.
    other = Var("otherVar", _var_data=VarData()).to(str)
    comp.special_props = [other]
    assert "_vars_cache" not in comp.__dict__
    recomputed = list(comp._get_vars())
    assert any(v._js_expr == "otherVar" for v in recomputed)
    # And the recompute re-primes the cache.
    assert "_vars_cache" in comp.__dict__


def test_direct_vars_build_matches_get_vars():
    # The direct mirror-built harvest must equal what _get_vars computes
    # on the same instance: same exprs, same var_data, same order.
    fixtures = [
        lambda: rx.input(value=_STATE_VAR, placeholder="p"),
        lambda: rx.text("hi", size="3", class_name="a b", key="k", id="i"),
        lambda: rx.text("sty", color=_STATE_VAR, _hover={"color": "red"}),
        lambda: rx.button("ev", on_click=rx.console_log("x")),
        lambda: rx.el.div("attrs", custom_attrs={"data-x": _STATE_VAR}),
        lambda: rx.text(f"embedded {_STATE_VAR} tail"),
    ]
    for build in fixtures:
        with arena_construction():
            comp = build()
        direct = comp.__dict__.pop("_vars_cache", None)
        assert direct is not None
        recomputed = tuple(comp._get_vars())
        assert len(direct) == len(recomputed)
        for a, b in zip(direct, recomputed, strict=True):
            assert a._js_expr == b._js_expr
            assert (a._get_all_var_data() is None) == (b._get_all_var_data() is None)


def test_scope_is_context_local():
    from reflex_base.components.component import _ARENA_CONSTRUCTION

    assert _ARENA_CONSTRUCTION.get() is False
    with arena_construction():
        assert _ARENA_CONSTRUCTION.get() is True
        with arena_construction(False):
            assert _ARENA_CONSTRUCTION.get() is False
        assert _ARENA_CONSTRUCTION.get() is True
    assert _ARENA_CONSTRUCTION.get() is False
