"""Gate for the scalar ``LiteralVar.create`` -> Rust cutover.

Non-string scalars (``int``/``float``/``bool``/``None``) created via the public
``LiteralVar.create`` now produce the Rust-backed literal var. These tests pin
the observable behavior of that cutover: the produced type, byte-identical
rendering (including the ``1.0`` / ``Infinity`` / ``NaN`` float edge cases), the
``json()`` contract, and the operator type-validation that the typed Python
``Var`` classes enforced (so invalid operations still raise and valid ones still
render).
"""

from __future__ import annotations

import math
import operator
from typing import TypedDict

import pytest
from reflex_base.utils.exceptions import PrimitiveUnserializableToJSONError
from reflex_base.vars.base import LiteralVar, Var
from reflex_compiler_rust._native import LiteralVar as RustLiteralVar


@pytest.mark.parametrize(
    "value", [5, -7, 0, 1.5, 1.0, 100.0, True, False, None, "hi", "", 'a"b']
)
def test_scalar_create_returns_rust_literal(value: object) -> None:
    """Scalars (including plain strings) route to the Rust literal var."""
    assert isinstance(LiteralVar.create(value), RustLiteralVar)


def test_string_serializes_to_value() -> None:
    """A routed string literal serializes back to its Python value."""
    from reflex_base.utils.format import json_dumps

    assert json_dumps([1, LiteralVar.create("hi")]) == '[1, "hi"]'


def test_fstring_single_var_is_not_literal() -> None:
    """An f-string of a single state var decodes to the var (not a fake literal)."""
    import reflex as rx

    class _S(rx.State):
        name: str = "x"

    var = LiteralVar.create(f"{_S.name}")
    # The single embedded var is returned (a plain expression), not wrapped as a
    # bogus literal whose value is the marker string.
    assert not isinstance(var, RustLiteralVar)
    assert "name" in var._js_expr


def test_fstring_all_literal_folds_to_literal() -> None:
    """An f-string whose parts are all literals folds to a single literal."""
    inner = LiteralVar.create("p")
    folded = LiteralVar.create(f"foo{inner}bar")
    assert isinstance(folded, RustLiteralVar)
    assert str(folded) == '"foopbar"'


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "1.0"),
        (100.0, "100.0"),
        (1.5, "1.5"),
        (5, "5"),
        (True, "true"),
        (None, "null"),
    ],
)
def test_scalar_rendering(value: object, expected: str) -> None:
    """Scalar rendering is byte-identical to the historical Python output."""
    assert str(LiteralVar.create(value)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(math.inf, "Infinity"), (-math.inf, "-Infinity"), (math.nan, "NaN")],
)
def test_non_finite_float_rendering(value: float, expected: str) -> None:
    """inf/nan render as their JS globals and raise on json()."""
    var = LiteralVar.create(value)
    assert str(var) == expected
    with pytest.raises(PrimitiveUnserializableToJSONError):
        var.json()


def test_scalar_json() -> None:
    """Finite scalar json() round-trips through json.dumps."""
    assert LiteralVar.create(5).json() == "5"
    assert LiteralVar.create(1.5).json() == "1.5"
    assert LiteralVar.create(True).json() == "true"


@pytest.mark.parametrize(
    "op",
    [
        operator.add,
        operator.sub,
        operator.truediv,
        operator.floordiv,
        operator.mod,
        operator.pow,
    ],
)
def test_number_op_with_non_number_raises(op) -> None:
    """A numeric var operation against a non-number raises (both directions)."""
    number = LiteralVar.create(5)
    array = LiteralVar.create([1, 2])
    with pytest.raises(TypeError):
        op(number, array)
    with pytest.raises(TypeError):
        op(array, number)


@pytest.mark.parametrize("op", [operator.lt, operator.le, operator.gt, operator.ge])
def test_number_comparison_with_non_number_raises(op) -> None:
    """Ordering a numeric var against a non-number raises."""
    number = LiteralVar.create(5)
    array = LiteralVar.create([1, 2])
    with pytest.raises(TypeError):
        op(number, array)


def test_number_times_array_repeats() -> None:
    """``number * array`` stays valid (array repeat), same as ``array * number``."""
    number = LiteralVar.create(5)
    array = LiteralVar.create([1, 2])
    expected = "Array.from({ length: 5 }).flatMap(() => [1, 2])"
    assert str(number * array) == expected
    assert str(array * number) == expected


def test_strict_float_array_repeat_raises() -> None:
    """A strict-float count cannot repeat an array."""
    array = LiteralVar.create([1, 2])
    with pytest.raises(TypeError):
        _ = LiteralVar.create(1.5) * array


def test_number_arithmetic_still_works() -> None:
    """Number-number arithmetic renders unchanged."""
    five = LiteralVar.create(5)
    assert str(five + LiteralVar.create(3)) == "(5 + 3)"
    assert str(five > LiteralVar.create(3)) == "(5 > 3)"


def test_var_create_scalar_is_rust() -> None:
    """The public ``Var.create`` also routes scalars to Rust."""
    assert isinstance(Var.create(5), RustLiteralVar)


@pytest.mark.parametrize(
    "value",
    [[1, 2, 3], ["a", "b"], [[1, 2], [3]], {"a": 1}, {"a": {"b": 1}}, [], {}],
)
def test_container_create_returns_rust_literal(value: object) -> None:
    """Plain list/dict literals route to the Rust literal var."""
    assert isinstance(LiteralVar.create(value), RustLiteralVar)


def test_dict_json_format() -> None:
    """Object json renders ``{k:v}`` (colon, no space) like LiteralObjectVar."""
    assert LiteralVar.create({"a": 1, "b": 2}).json() == '{"a":1, "b":2}'


def test_list_json_format() -> None:
    """Array json renders ``[a, b]`` like LiteralArrayVar."""
    assert LiteralVar.create([1, [2, 3]]).json() == "[1, [2, 3]]"


def test_container_with_embedded_var_var_data() -> None:
    """A container literal aggregates an embedded var's var_data."""
    import reflex as rx

    class _S(rx.State):
        x: int = 0

    var = LiteralVar.create([1, _S.x])
    assert "x" in var._js_expr
    assert var._get_all_var_data() is not None


def test_container_element_type_inferred() -> None:
    """List/dict var_type uses figure_out_type (Sequence[int], Mapping[str,int])."""
    from collections.abc import Mapping, Sequence

    assert LiteralVar.create([1, 2, 3])._var_type == Sequence[int]
    assert LiteralVar.create({"a": 1})._var_type == Mapping[str, int]


class _Post(TypedDict):
    url: str
    views: int


def test_typeddict_item_access_narrows_to_field_type() -> None:
    """String-key and attribute access on a TypedDict-typed var yield the
    field's annotated type.

    Regression: TypedDict classes subclass ``dict`` (a registered ``Mapping``),
    so object item access took the mapping value-type path, found no
    ``__args__``, and fell back to the TypedDict type itself — making
    ``post["url"]`` fail ``str`` prop validation downstream.
    """
    import reflex as rx

    class _S(rx.State):
        posts: list[_Post] = []
        scores: dict[str, int] = {}

    item = _S.posts[0]
    assert item._var_type is _Post
    assert item["url"]._var_type is str
    assert item["views"]._var_type is int
    assert item.url._var_type is str
    # Plain mapping types still narrow to the mapping value type.
    assert _S.scores["k"]._var_type is int


def test_to_objectvar_cast_supports_attr_and_item_access() -> None:
    """A Python var cast via ``.to(ObjectVar)`` supports attribute/item access.

    Regression: the cutover deleted ``ObjectVar.__getattr__``, so ``ToOperation``
    casts (e.g. ``rx.scroll_to``'s ``document.getElementById(...).to(ObjectVar)``)
    raised ``VarAttributeError`` on any attribute access.
    """
    from reflex_base.vars.base import FunctionStringVar, ObjectVar

    import reflex as rx

    spec = rx.scroll_to("download-button")
    assert "scrollIntoView" in str(spec.args[0][1])

    obj = FunctionStringVar.create("document.getElementById").call("x").to(ObjectVar)
    assert str(obj.focus) == '(document.getElementById("x"))?.["focus"]'
    assert str(obj["focus"]) == '(document.getElementById("x"))?.["focus"]'


def test_function_cast_native_var_is_callable() -> None:
    """Direct-call syntax on a ``.to(FunctionVar)`` native var works like ``.call``.

    Regression: ``reflex_enterprise``'s PassthroughAPI does
    ``getattr(api, name)(*args)``; the native var exposed ``call`` but not
    ``__call__``, so the call raised ``TypeError: not callable``.
    """
    from reflex_base.vars.base import FunctionStringVar, FunctionVar, ObjectVar

    api = FunctionStringVar.create("document.getElementById").call("x").to(ObjectVar)
    fn = api.selectAll.to(FunctionVar)
    assert str(fn(True)) == str(fn.call(True))
    assert str(fn()) == str(fn.call())


def test_objectvar_get_method() -> None:
    """``.get(key, default)`` on an object var renders ``cond(value, value, default)``.

    Regression: the cutover dropped ``ObjectVar.get``, so ``.get`` resolved as
    a field access whose result wasn't callable.
    """
    import reflex as rx

    class _S(rx.State):
        d: dict[str, str] = {}

    item = str(_S.d["name"])
    with_default = str(_S.d.get("name", "Unknown"))
    assert item in with_default
    assert '"Unknown"' in with_default
    no_default = str(_S.d.get("name"))
    assert item in no_default
    assert "null" in no_default


def test_objectvar_underscore_string_key_item_access() -> None:
    """A leading-underscore string key resolves as item access.

    Only dunder names are refused, matching pre-cutover ``ObjectVar.__getattr__``
    (regression: ``reflex_enterprise`` map events read ``...to(dict)["_zoom"]``).
    """
    import reflex as rx

    class _S(rx.State):
        d: dict[str, int] = {}

    v = _S.d["_zoom"]
    assert v._var_type is int
    assert str(v).endswith('?.["_zoom"]')
    cast = _S.d.to(dict)["_zoom"]
    assert str(cast).endswith('?.["_zoom"]')


def test_bare_dict_item_access_narrows_to_any() -> None:
    """Item access on a bare ``dict``-typed var yields ``Any``, not ``dict``.

    Regression: the mapping value-type lookup fell back to the receiver's own
    type when ``__args__`` was missing, so ``data["color"]`` stayed
    dict-typed and failed prop validation (reflex_enterprise react-flow memo).
    """
    from typing import Any

    import reflex as rx

    class _S(rx.State):
        d: dict = {}

    assert _S.d["color"]._var_type is Any
    assert _S.d.to(dict)["color"]._var_type is Any


def test_event_chain_with_cond_var_event() -> None:
    """A chain event that is a Var (``rx.cond`` of two EventSpecs) renders
    wrapped in the invocation, like the pre-cutover
    ``invocation.call(LiteralVar.create([event]), ...)`` form.

    Regression: the Rust assembler discriminated events via
    ``hasattr(event, "handler")``, which is true for a spec-*typed* Var, so it
    read ``event.args`` (an item-access var) and raised on iterating it.
    """
    import reflex as rx

    class _S(rx.State):
        flag: bool = False

        def a(self):
            pass

        def b(self):
            pass

    btn = rx.el.button(on_click=rx.cond(_S.flag, _S.a(), _S.b()))
    chain_var = LiteralVar.create(btn.event_triggers["on_click"])
    rendered = str(chain_var)
    assert "addEvents([(" in rendered
    assert '.a"' in rendered
    assert '.b"' in rendered
    var_data = chain_var._get_all_var_data()
    assert var_data is not None
    # The cond var's own var_data (its state ref) must flow into the chain's.
    assert var_data.state
    assert any("StateContexts" in hook for hook in var_data.hooks)


def test_function_module_constants_reexported() -> None:
    """``reflex.vars.function`` still exposes the public function constants.

    Regression: the cutover shim dropped ``ARRAY_ISARRAY`` /
    ``JSON_STRINGIFY`` / ``PROTOTYPE_TO_STRING`` (used by downstream code,
    e.g. reflex-site-shared headings).
    """
    from reflex.vars import function, sequence

    rendered = str(function.ARRAY_ISARRAY(LiteralVar.create([])))
    assert rendered == "(Array.isArray([]))"
    assert str(function.JSON_STRINGIFY) == "JSON.stringify"
    assert "toString" in str(function.PROTOTYPE_TO_STRING)
    mapped = str(
        sequence.map_array_operation(
            LiteralVar.create([1, 2]), function.PROTOTYPE_TO_STRING
        )
    )
    assert ".map(" in mapped


def test_custom_registered_subclass_uses_base_category_for_ops() -> None:
    """A var typed as a custom registered subclass (e.g. ``ReflexURL`` →
    ``ReflexURLVar``) dispatches operators via its standard base category.

    Regression: ``rx.State.router.url + "#frag"`` raised ``VarTypeError:
    Unsupported Operand type(s) for +: NumberVar, str`` because
    ``var_category`` returned the custom subclass name verbatim and the
    operator dispatch only knows the standard categories.
    """
    import reflex as rx

    url = rx.State.router.url
    joined = url + "#frag"
    assert joined._js_expr.endswith('+"#frag")')
    prefixed = "go: " + url
    assert prefixed._js_expr.startswith('("go: "+')
