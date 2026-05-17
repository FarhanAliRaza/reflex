"""Tests for experimental memo support."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from reflex_base.components.component import CUSTOM_COMPONENTS, Component
from reflex_base.style import Style
from reflex_base.utils.imports import ImportVar
from reflex_base.vars import VarData
from reflex_base.vars.base import Var
from reflex_base.vars.function import FunctionVar

import reflex as rx
from reflex.compiler import compiler
from reflex.compiler import utils as compiler_utils
from reflex.experimental.memo import (
    EXPERIMENTAL_MEMOS,
    ExperimentalMemoComponent,
    ExperimentalMemoComponentDefinition,
    ExperimentalMemoFunctionDefinition,
    create_passthrough_component_memo,
    peek_memoize,
)


@pytest.fixture(autouse=True)
def _restore_memo_registries(preserve_memo_registries):
    """Autouse wrapper around the shared preserve_memo_registries fixture."""


def test_var_returning_memo():
    """Var-returning memos should behave like imported function vars."""

    @rx._x.memo
    def format_price(amount: rx.Var[int], currency: rx.Var[str]) -> rx.Var[str]:
        return currency.to(str) + ": $" + amount.to(str)

    price = Var(_js_expr="price", _var_type=int)
    currency = Var(_js_expr="currency", _var_type=str)

    assert (
        str(format_price(amount=price, currency=currency))
        == "(format_price(price, currency))"
    )
    assert (
        str(format_price.call(amount=price, currency=currency))
        == "(format_price(price, currency))"
    )
    assert isinstance(format_price._as_var(), FunctionVar)

    definition = EXPERIMENTAL_MEMOS["format_price"]
    assert isinstance(definition, ExperimentalMemoFunctionDefinition)
    assert (
        str(definition.function) == '((amount, currency) => ((currency+": $")+amount))'
    )

    with pytest.raises(TypeError, match="only accepts keyword props"):
        format_price(price, currency)


def test_component_returning_memo_with_children_and_rest():
    """Component-returning memos should accept positional children and forwarded props."""

    @rx._x.memo
    def my_card(
        children: rx.Var[rx.Component],
        rest: rx.RestProp,
        *,
        title: rx.Var[str],
    ) -> rx.Component:
        return rx.box(
            rx.heading(title),
            children,
            rest,
        )

    component = my_card(
        rx.text("child 1"),
        rx.text("child 2"),
        title="Hello",
        foo="extra",
        class_name="extra",
    )
    component_again = my_card(title="World")

    assert isinstance(component, ExperimentalMemoComponent)
    assert len(component.children) == 2
    assert component.get_props() == ("title", "foo")
    assert type(component) is type(component_again)
    assert type(component).tag == "MyCard"
    assert type(component).get_fields()["tag"].default == "MyCard"

    rendered = component.render()
    assert rendered["name"] == "MyCard"
    assert 'title:"Hello"' in rendered["props"]
    assert 'foo:"extra"' in rendered["props"]
    assert 'className:"extra"' in rendered["props"]

    definition = EXPERIMENTAL_MEMOS["MyCard"]
    assert isinstance(definition, ExperimentalMemoComponentDefinition)
    assert any(str(prop) == "rest" for prop in definition.component.special_props)

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)
    assert "export const MyCard = memo(({children, title:title" in code
    assert "...rest" in code
    assert "jsx(RadixThemesBox,{...rest}" in code


def test_component_returning_memo_accepts_component_var_result():
    """Component-returning memos should accept component-typed var results."""

    @rx._x.memo
    def conditional_slot(
        show: rx.Var[bool],
        first: rx.Var[rx.Component],
        second: rx.Var[rx.Component],
    ) -> rx.Var[rx.Component]:
        return rx.cond(show, first, second)

    definition = EXPERIMENTAL_MEMOS["ConditionalSlot"]
    assert isinstance(definition, ExperimentalMemoComponentDefinition)
    assert definition.component.render() == {
        "contents": "(showRxMemo ? firstRxMemo : secondRxMemo)"
    }

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)
    assert "export const ConditionalSlot = memo(({show:showRxMemo" in code
    assert "(showRxMemo ? firstRxMemo : secondRxMemo)" in code


def test_var_returning_memo_with_rest_props():
    """Var-returning memos should capture extra keyword args into RestProp."""

    @rx._x.memo
    def merge_styles(
        base: rx.Var[dict[str, str]],
        overrides: rx.RestProp,
    ) -> rx.Var[Any]:
        return base.to(dict).merge(overrides)

    base = Var(_js_expr="base", _var_type=dict[str, str])
    merged = merge_styles(base=base, color="red", class_name="primary")

    assert "merge_styles" in str(merged)
    assert '["base"] : base' in str(merged)
    assert '["color"] : "red"' in str(merged)
    assert '["className"] : "primary"' in str(merged)

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)
    assert (
        "export const merge_styles = (({base, ...overrides}) => ({...base, ...overrides}));"
        in code
    )

    with pytest.raises(TypeError, match="Do not pass `overrides=` directly"):
        merge_styles(base=base, overrides={"color": "red"})


def test_component_returning_memo_with_only_rest():
    """Component-returning memos with only RestProp should emit valid JSX (#6443)."""

    @rx._x.memo
    def hover_trigger(rest: rx.RestProp) -> rx.Component:
        return rx.text("hover me", rest)

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)
    assert "memo(({...rest})" in code
    assert "({," not in code


def test_var_returning_memo_with_only_rest():
    """Var-returning memos with only RestProp should emit valid JS (#6443)."""

    @rx._x.memo
    def merge_only(overrides: rx.RestProp) -> rx.Var[Any]:
        return overrides

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)
    assert "(({...overrides}) => overrides)" in code
    assert "({," not in code


def test_var_returning_memo_with_children_and_rest():
    """Var-returning memos should accept positional children plus keyword props."""

    @rx._x.memo
    def label_slot(
        children: rx.Var[rx.Component],
        rest: rx.RestProp,
        *,
        label: rx.Var[str],
    ) -> rx.Var[str]:
        return label

    rendered = label_slot(
        rx.text("child"),
        label="Hello",
        class_name="slot",
    )

    assert "label_slot" in str(rendered)
    assert '["children"]' in str(rendered)
    assert '["className"] : "slot"' in str(rendered)

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)
    assert "export const label_slot = (({children, label, ...rest}) => label);" in code


def test_memo_requires_var_annotations():
    """Experimental memos should require Var annotations on parameters."""
    with pytest.raises(TypeError, match="must be annotated"):

        @rx._x.memo
        def bad_annotation(value: int) -> rx.Var[str]:
            return rx.Var.create("x")

    with pytest.raises(TypeError, match="Missing annotation"):

        @rx._x.memo
        def missing_annotation(value) -> rx.Var[str]:
            return rx.Var.create("x")


def test_memo_rejects_invalid_children_annotation():
    """Component memos should validate the special children annotation."""
    with pytest.raises(TypeError, match="children"):

        @rx._x.memo
        def bad_children(children: rx.Var[str]) -> rx.Component:
            return rx.text(children)


def test_memo_rejects_multiple_rest_props():
    """Experimental memos should only allow a single RestProp."""
    with pytest.raises(TypeError, match="only supports one"):

        @rx._x.memo
        def too_many_rest(
            first: rx.RestProp,
            second: rx.RestProp,
        ) -> rx.Var[Any]:
            return first


def test_memo_rejects_component_and_function_name_collision():
    """Experimental memos should reject same exported name across kinds."""

    @rx._x.memo
    def foo_bar() -> rx.Component:
        return rx.box()

    assert "FooBar" in EXPERIMENTAL_MEMOS

    with pytest.raises(ValueError, match=r"name collision.*FooBar"):

        @rx._x.memo
        def FooBar() -> rx.Var[str]:
            return rx.Var.create("x")


def test_memo_rejects_component_export_name_collision():
    """Experimental memos should reject duplicate component export names."""

    @rx._x.memo
    def foo_bar() -> rx.Component:
        return rx.box()

    with pytest.raises(ValueError, match=r"name collision.*FooBar"):

        @rx._x.memo
        def foo__bar() -> rx.Component:
            return rx.box()


def test_memo_rejects_varargs():
    """Experimental memos should reject *args and **kwargs."""
    with pytest.raises(TypeError, match=r"\*args"):

        @rx._x.memo
        def bad_args(*values: rx.Var[str]) -> rx.Var[str]:
            return rx.Var.create("x")

    with pytest.raises(TypeError, match=r"\*\*kwargs"):

        @rx._x.memo
        def bad_kwargs(**values: rx.Var[str]) -> rx.Var[str]:
            return rx.Var.create("x")


def test_component_memo_rejects_invalid_positional_usage():
    """Component memos should only accept positional children."""

    @rx._x.memo
    def title_card(*, title: rx.Var[str]) -> rx.Component:
        return rx.box(rx.heading(title))

    with pytest.raises(TypeError, match="only accepts keyword props"):
        title_card(rx.text("child"))

    @rx._x.memo
    def child_card(
        children: rx.Var[rx.Component], *, title: rx.Var[str]
    ) -> rx.Component:
        return rx.box(rx.heading(title), children)

    with pytest.raises(TypeError, match="only accepts positional children"):
        child_card("not a component", title="Hello")


def test_var_memo_rejects_invalid_positional_usage():
    """Var memos should also reserve positional arguments for children only."""

    @rx._x.memo
    def format_price(amount: rx.Var[int], currency: rx.Var[str]) -> rx.Var[str]:
        return currency.to(str) + ": $" + amount.to(str)

    price = Var(_js_expr="price", _var_type=int)
    currency = Var(_js_expr="currency", _var_type=str)

    with pytest.raises(TypeError, match="only accepts keyword props"):
        format_price(price, currency)

    @rx._x.memo
    def child_label(
        children: rx.Var[rx.Component], *, label: rx.Var[str]
    ) -> rx.Var[str]:
        return label

    with pytest.raises(TypeError, match="only accepts positional children"):
        child_label("not a component", label="Hello")


def test_var_returning_memo_rejects_hooks():
    """Var-returning memos should reject hook-bearing expressions."""
    with pytest.raises(TypeError, match="cannot depend on hooks"):

        @rx._x.memo
        def bad_hook(value: rx.Var[str]) -> rx.Var[str]:
            return Var(
                _js_expr="value",
                _var_type=str,
                _var_data=VarData(hooks={"const badHook = 1": None}),
            )


def test_var_returning_memo_rejects_non_bundled_imports():
    """Var-returning memos should reject non-bundled imports."""
    with pytest.raises(TypeError, match="not bundled"):

        @rx._x.memo
        def bad_import(value: rx.Var[str]) -> rx.Var[str]:
            return Var(
                _js_expr="value",
                _var_type=str,
                _var_data=VarData(imports={"some-lib": [ImportVar(tag="x")]}),
            )


def test_compile_memo_components_includes_experimental_functions_and_components():
    """The shared memo output should include both experimental functions and components."""

    @rx.memo
    def old_wrapper(title: rx.Var[str]) -> rx.Component:
        return rx.text(title)

    @rx._x.memo
    def format_price(amount: rx.Var[int], currency: rx.Var[str]) -> rx.Var[str]:
        return currency.to(str) + ": $" + amount.to(str)

    @rx._x.memo
    def my_card(children: rx.Var[rx.Component], *, title: rx.Var[str]) -> rx.Component:
        return rx.box(rx.heading(title), children)

    files, _ = compiler.compile_memo_components(
        dict.fromkeys(CUSTOM_COMPONENTS.values()),
        tuple(EXPERIMENTAL_MEMOS.values()),
    )
    code = "\n".join(c for _, c in files)

    assert "export const OldWrapper = memo(" in code
    assert "export const format_price =" in code
    assert "export const MyCard = memo(" in code


def test_compile_memo_components_extends_imports_without_remerging(
    monkeypatch: pytest.MonkeyPatch,
):
    """Memo import aggregation should not repeatedly reprocess prior imports."""

    def noop() -> None:
        pass

    memos = tuple(
        ExperimentalMemoComponentDefinition(
            fn=noop,
            python_name=f"memo_{idx}",
            params=(),
            export_name=f"Memo{idx}",
            component=rx.fragment(),
            passthrough_hole_child=None,
        )
        for idx in range(5)
    )

    def fake_compile_experimental_component_memo(
        definition: ExperimentalMemoComponentDefinition,
    ) -> tuple[dict[str, str], dict[str, list[ImportVar]]]:
        return {"name": definition.export_name}, {}

    def fake_compile_single_memo_component(
        component_render: dict[str, str],
        component_imports: dict[str, list[ImportVar]],
    ) -> tuple[str, dict[str, list[ImportVar]]]:
        return (
            f"export const {component_render['name']} = null",
            {"shared-lib": [ImportVar(tag=component_render["name"])]},
        )

    real_merge_imports = compiler_utils.merge_imports

    def reject_growing_merge(*imports):
        if len(imports) == 2 and imports[0]:
            msg = "aggregate imports should be extended, not remerged"
            raise AssertionError(msg)
        return real_merge_imports(*imports)

    monkeypatch.setattr(
        compiler_utils,
        "compile_experimental_component_memo",
        fake_compile_experimental_component_memo,
    )
    monkeypatch.setattr(
        compiler,
        "_compile_single_memo_component",
        fake_compile_single_memo_component,
    )
    monkeypatch.setattr(compiler_utils, "merge_imports", reject_growing_merge)

    files, aggregate_imports = compiler.compile_memo_components((), memos)

    assert len(files) == len(memos) + 1
    assert [import_var.tag for import_var in aggregate_imports["shared-lib"]] == [
        f"Memo{idx}" for idx in range(5)
    ]


def test_experimental_component_memo_get_imports():
    """Experimental component memos should resolve imports during compilation."""

    class Inner(Component):
        tag = "Inner"
        library = "inner"

    @rx._x.memo
    def wrapper() -> rx.Component:
        return Inner.create()

    experimental_component = wrapper()

    assert "inner" not in experimental_component._get_all_imports()

    definition = EXPERIMENTAL_MEMOS["Wrapper"]
    assert isinstance(definition, ExperimentalMemoComponentDefinition)
    _, imports = compiler_utils.compile_experimental_component_memo(definition)
    assert "inner" in imports


def test_compile_experimental_component_memo_does_not_mutate_definition(
    monkeypatch: pytest.MonkeyPatch,
):
    """Experimental component memo compilation should not mutate stored components."""

    @rx._x.memo
    def wrapper() -> rx.Component:
        return rx.box("hi")

    definition = EXPERIMENTAL_MEMOS["Wrapper"]
    assert isinstance(definition, ExperimentalMemoComponentDefinition)
    assert definition.component.style == Style()

    monkeypatch.setattr(
        "reflex.utils.prerequisites.get_and_validate_app",
        lambda: SimpleNamespace(
            app=SimpleNamespace(
                style={type(definition.component): Style({"color": "red"})}
            )
        ),
    )

    render, _ = compiler_utils.compile_experimental_component_memo(definition)

    assert render["render"]["props"] == ['css:({ ["color"] : "red" })']
    assert definition.component.style == Style()


def test_component_returning_memo_is_transparent_for_child_validation():
    """Experimental memo wrappers should not break `_valid_parents` checks."""

    class ValidParent(Component):
        tag = "ValidParent"
        library = "valid-parent"

    class RestrictedChild(Component):
        tag = "RestrictedChild"
        library = "restricted-child"
        _valid_parents = ["ValidParent"]

    @rx._x.memo
    def transparent(children: rx.Var[rx.Component]) -> rx.Component:
        return children  # type: ignore[return-value]

    wrapped_child = transparent(RestrictedChild.create())
    parent = ValidParent.create(wrapped_child)

    assert isinstance(wrapped_child, ExperimentalMemoComponent)
    assert parent.children == [wrapped_child]


def test_compile_memo_components_includes_experimental_custom_code():
    """Experimental component memos should include custom code in compiled output."""

    class FooComponent(rx.Fragment):
        def add_custom_code(self) -> list[str]:
            return [
                "const foo = 'bar'",
            ]

    @rx._x.memo
    def foo_component(label: rx.Var[str]) -> rx.Component:
        return FooComponent.create(label, rx.Var("foo"))

    files, _ = compiler.compile_memo_components((), tuple(EXPERIMENTAL_MEMOS.values()))
    code = "\n".join(c for _, c in files)

    assert "const foo = 'bar'" in code


# ---------------------------------------------------------------------------
# peek_memoize: cheap preview used by the Rust IR memoize port.
# Hash parity with create_passthrough_component_memo is gating.
# ---------------------------------------------------------------------------


def _signature_for(definition: ExperimentalMemoComponentDefinition) -> str:
    """Reconstruct the JS signature cppm would emit for a definition.

    cppm produces ``"({ children })"`` when a passthrough hole was substituted
    in (``definition.passthrough_hole_child is not None``) and ``"()"``
    otherwise. peek's third tuple element must match this exactly so Phase 2
    JSX emission stays byte-identical.

    Args:
        definition: The cppm component definition.

    Returns:
        The expected signature string.
    """
    return "({ children })" if definition.passthrough_hole_child is not None else "()"


def _peek_corpus():
    """Build the gating hash-parity corpus.

    Each entry is ``(label, component)``. Cases are kept inside this factory
    rather than as module-level constants so that custom subclasses created
    during the test run are torn down between tests by
    ``preserve_memo_registries``.

    Returns:
        A list of ``(label, component)`` tuples.
    """
    box_with_children = rx.box(rx.text("a"), rx.text("b"), class_name="outer")
    box_empty = rx.box(class_name="solo")
    # rx.upload is a MemoizationLeaf — snapshot boundary.
    snapshot = rx.upload(rx.text("drop"), id="dropzone")
    # Form exercises the ``_get_all_refs`` rebinding path (Form._get_form_refs
    # walks descendants to build the submit handler's field map).
    form = rx.el.form(
        rx.el.input(id="name", name="name"),
        rx.el.input(id="email", name="email"),
    )
    # Outer wrapping an already-memoized inner: peek on the outer must NOT
    # recurse into the inner. We assert that by hashing inner separately and
    # confirming the outer's hash is independent of recursive peek.
    inner_for_nested = rx.box(rx.text("inner-content"), class_name="inner")
    nested_outer = rx.box(inner_for_nested, class_name="outer-of-nested")
    return [
        ("box_with_children", box_with_children),
        ("box_empty", box_empty),
        ("snapshot_upload", snapshot),
        ("form_with_refs", form),
        ("nested_outer", nested_outer),
    ]


@pytest.mark.parametrize(
    ("label", "component"),
    _peek_corpus(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_peek_memoize_hash_parity(label: str, component: Component):
    """peek_memoize must return the same export_name + signature as cppm.

    This is the gating contract: Phase 2 (Rust IR memoize) consumes peek's
    output and writes ``.web/utils/components/<export_name>.jsx``. Any drift
    from cppm's export name silently strands cached JSX files.

    Args:
        label: Corpus entry label (for failure messages).
        component: Component under test.
    """
    name_peek, body_peek, sig_peek = peek_memoize(component)
    _, definition = create_passthrough_component_memo(component)

    assert name_peek == definition.export_name, (
        f"[{label}] export_name drift: peek={name_peek!r} cppm={definition.export_name!r}"
    )
    assert sig_peek == _signature_for(definition), (
        f"[{label}] signature drift: peek={sig_peek!r} cppm={_signature_for(definition)!r}"
    )
    # Body equality via _compute_memo_tag round-trip: if the post-lift bodies
    # have any structural difference (placeholder _js_expr, _var_data, child
    # ordering, special_props), the tag hash diverges. cppm stores the
    # post-lift component in definition.component (lifted in-place inside
    # _create_component_definition).
    assert body_peek._compute_memo_tag() == definition.component._compute_memo_tag(), (
        f"[{label}] body hash drift after lift"
    )
    # And the rendered dicts must match structurally too (catches placeholder
    # var-data drift that _compute_memo_tag's shallow mode might miss).
    assert body_peek.render() == definition.component.render(), (
        f"[{label}] rendered body drift"
    )


def test_peek_memoize_returns_documented_tuple_shape():
    """peek_memoize must return a 3-tuple of (str, Component, str)."""
    result = peek_memoize(rx.box(rx.text("x")))
    assert isinstance(result, tuple)
    assert len(result) == 3
    name, body, signature = result
    assert isinstance(name, str)
    assert name
    assert isinstance(body, Component)
    assert signature in {"({ children })", "()"}


def test_peek_memoize_does_not_mutate_input():
    """peek_memoize must leave the input component untouched.

    Phase 2 calls peek on live page-tree nodes; mutation would corrupt the
    user-authored subtree and downstream walkers (Form._get_form_refs,
    plugin._get_all_refs delegation) would observe stale state.
    """
    component = rx.box(rx.text("hello"), class_name="probe")
    before_children = list(component.children)
    before_special = list(component.special_props)
    before_get_all_refs = type(component)._get_all_refs

    peek_memoize(component)

    assert component.children == before_children
    assert component.special_props == before_special
    # The bound method on the instance must still be the class method, i.e.
    # peek must not have rebound _get_all_refs on the source via setattr.
    assert "_get_all_refs" not in component.__dict__
    assert type(component)._get_all_refs is before_get_all_refs


def test_peek_memoize_is_idempotent():
    """Calling peek_memoize twice on the same component must return equal tuples."""
    component = rx.box(rx.text("x"), rx.text("y"), class_name="probe")
    first = peek_memoize(component)
    second = peek_memoize(component)
    assert first[0] == second[0]
    assert first[2] == second[2]
    assert first[1].render() == second[1].render()
    assert first[1]._compute_memo_tag() == second[1]._compute_memo_tag()


def test_peek_memoize_signature_for_empty_passthrough_is_no_args():
    """Passthrough with no original children should yield ``()`` signature.

    Mirrors cppm's behavior: when ``component.children`` is empty, no hole is
    inserted (see ``_build_passthrough_body``) so the wrapper signature has
    no destructured ``children`` parameter.
    """
    component = rx.box(class_name="empty")
    _, _, signature = peek_memoize(component)
    assert signature == "()"


def test_peek_memoize_signature_for_snapshot_is_no_args():
    """Snapshot-boundary components also yield ``()`` (no hole)."""
    component = rx.upload(rx.text("drop"), id="dz")
    _, _, signature = peek_memoize(component)
    assert signature == "()"


def test_peek_memoize_rest_props_corpus():
    """A snapshot component with RestProp children must lift identically to cppm.

    In passthrough mode the outer ``children`` are replaced by the
    ``{children}`` hole, so any RestProp directly under the outer is lost.
    The lifting path is meaningful for snapshot-boundary components (which
    keep their original children), so we use a snapshot component here to
    exercise ``_lift_rest_props`` against both peek and cppm output.
    """
    from reflex_base.vars.object import RestProp
    from reflex_components_core.base.bare import Bare

    rest_prop = RestProp(_js_expr="extras", _var_type=dict[str, Any])
    # rx.upload is a snapshot boundary (MemoizationLeaf), so its children
    # survive into the body uncloned by the hole — _lift_rest_props can find
    # the RestProp child and promote it into special_props.
    component = rx.upload(Bare.create(rest_prop), rx.text("inner"), id="dz")

    name_peek, body_peek, _ = peek_memoize(component)
    _, definition = create_passthrough_component_memo(component)

    assert name_peek == definition.export_name
    # Comparing the rendered dicts is sufficient and the strictest check:
    # any difference in special_props or children renders as different JSX.
    assert body_peek.render() == definition.component.render()
    # Hash parity guarantees byte-equal special_props handling across peek
    # and cppm regardless of *where* in the tree the lift fires.
    assert body_peek._compute_memo_tag() == definition.component._compute_memo_tag()


def test_peek_memoize_does_not_recurse_into_inner_memo():
    """Peek on an outer component must hash its *literal* children.

    The Phase 2 Rust IR walker is responsible for memoizing inner candidates
    before peeking the outer; peek itself is intentionally non-recursive so
    callers control the walk order. Verify outer peek treats the inner as a
    plain child (no implicit recursion into another memo build).
    """
    inner = rx.box(rx.text("inner-content"), class_name="inner")
    outer = rx.box(inner, class_name="outer")

    name_outer, body_outer, _ = peek_memoize(outer)
    name_inner, _, _ = peek_memoize(inner)

    # Outer's hash must reflect inner's literal render, not a memoized stub.
    # Tag includes inner's full hash via the children render dict.
    assert name_outer != name_inner
    # Re-peeking inner after peeking outer must still be idempotent — outer's
    # call must not have mutated inner.
    name_inner_again, _, _ = peek_memoize(inner)
    assert name_inner == name_inner_again
    # Outer body's first child is still a Component (the inner box), not an
    # ExperimentalMemoComponent stub. peek_memoize is non-recursive.
    assert isinstance(body_outer.children[0], Component)
    assert not isinstance(body_outer.children[0], ExperimentalMemoComponent)
