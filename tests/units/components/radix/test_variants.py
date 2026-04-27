"""Regression tests for ``reflex_components_radix._variants.cn``.

The earlier implementation called ``p == ""`` and ``p == []`` on every
fragment, which raised ``VarTypeError`` when the docs site passed a
class-name composed from ``rx.cond`` (a Var). These tests pin the
behavior so that path stays open.
"""

from reflex_base.breakpoints import Breakpoints
from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.cond import cond
from reflex_components_radix._variants import cn, radius_class, responsive_classes


def test_cn_strings_only_returns_joined_string():
    assert cn("a", "b", "c") == "a b c"


def test_cn_drops_none_and_empty_strings():
    assert cn("a", None, "", "b") == "a b"


def test_cn_flattens_lists_and_tuples():
    assert cn(["a", "b"], ("c", "d"), "e") == "a b c d e"


def test_cn_passes_var_through_without_truthiness_check():
    # The docs site builds a class_name like
    # ``"base " + rx.cond(state.x, "scroll-mt-[113px]", "scroll-mt-[77px]")``
    # which evaluates to a Var. Calling ``cn(base_classes, that_var)`` used
    # to crash with VarTypeError; it must now pass the Var through and
    # return a list.
    var_class = cond(LiteralVar.create(True), "scroll-mt-[113px]", "scroll-mt-[77px]")
    out = cn("base", var_class)

    assert isinstance(out, list), f"expected list, got {type(out).__name__}: {out!r}"
    assert out[0] == "base"
    assert isinstance(out[1], Var)


def test_cn_passes_literal_var_through():
    out = cn("base", LiteralVar.create("dynamic"))
    assert isinstance(out, list)
    assert out[0] == "base"
    assert isinstance(out[1], Var)


def test_cn_var_inside_concatenated_string():
    # Mirrors the actual docs failure: a Python-level concatenation of
    # strings and a Var produces a single Var. ``cn`` should accept it.
    var_class = LiteralVar.create("base ") + cond(
        LiteralVar.create(True),
        "x",
        "y",
    )
    out = cn("prefix", var_class)
    assert isinstance(out, list)
    assert out[0] == "prefix"
    assert isinstance(out[1], Var)


# ----- responsive_classes ------------------------------------------------


def test_responsive_classes_returns_empty_for_none():
    assert responsive_classes(None, lambda v: f"grid-cols-{v}") == ""


def test_responsive_classes_str_value_uses_formatter_directly():
    assert responsive_classes("3", lambda v: f"grid-cols-{v}") == "grid-cols-3"


def test_responsive_classes_dict_emits_breakpoint_prefixed_classes():
    """The original Radix Themes API accepts ``columns={"base":"1","sm":"2","lg":"3"}``.
    The bridge must translate that to ``grid-cols-1 sm:grid-cols-2 lg:grid-cols-3``.
    """
    out = responsive_classes(
        {"base": "1", "sm": "2", "lg": "3"},
        lambda v: f"grid-cols-{v}",
    )
    assert out == "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"


def test_responsive_classes_breakpoints_subclass_works():
    """Reflex's ``Breakpoints`` is a dict subclass; treat it the same."""
    bp = Breakpoints({"base": "1", "md": "2"})
    assert (
        responsive_classes(bp, lambda v: f"grid-cols-{v}")
        == "grid-cols-1 md:grid-cols-2"
    )


def test_responsive_classes_initial_alias_for_base():
    """Reflex ``Breakpoints`` historically used ``initial`` for mobile-first."""
    out = responsive_classes(
        {"initial": "1", "md": "2"},
        lambda v: f"grid-cols-{v}",
    )
    assert out == "grid-cols-1 md:grid-cols-2"


def test_responsive_classes_skips_none_breakpoint_values():
    out = responsive_classes(
        {"base": "1", "md": None, "lg": "3"},
        lambda v: f"grid-cols-{v}",
    )
    assert out == "grid-cols-1 lg:grid-cols-3"


def test_responsive_classes_mapping_lookup_skips_unknown():
    """A formatter returning ``None`` (e.g. ``mapping.get`` for a stranger
    value) drops that breakpoint instead of producing a broken class.
    """
    mapping = {"row": "flex-row", "column": "flex-col"}
    out = responsive_classes(
        {"base": "row", "md": "diagonal", "lg": "column"},
        mapping.get,
    )
    assert out == "flex-row lg:flex-col"


def test_responsive_classes_multi_class_formatter_prefixes_each_token():
    """Mapping values can hold multiple classes — each must get the
    breakpoint prefix or Tailwind's JIT scan misses them.
    """
    mapping = {
        "center": "items-center justify-center",
        "start": "items-start justify-start",
    }
    out = responsive_classes(
        {"base": "start", "md": "center"},
        mapping.get,
    )
    assert out == "items-start justify-start md:items-center md:justify-center"


def test_responsive_classes_returns_empty_for_var_value():
    """Vars can't be translated at compile time; the helper returns ``""``
    so callers can fall back to leaving the prop on the element.
    """
    var = cond(LiteralVar.create(True), "1", "2")
    assert responsive_classes(var, lambda v: f"grid-cols-{v}") == ""


# ----- radius_class -----------------------------------------------------


def test_radius_class_full_maps_to_rounded_full():
    assert radius_class("full") == "rounded-full"


def test_radius_class_named_values_use_radix_radius_vars():
    assert radius_class("none") == "rounded-none"
    assert radius_class("small") == "rounded-(--radius-2)"
    assert radius_class("medium") == "rounded-(--radius-3)"
    assert radius_class("large") == "rounded-(--radius-4)"


def test_radius_class_responsive_dict_works():
    out = radius_class({"base": "medium", "md": "full"})
    assert out == "rounded-(--radius-3) md:rounded-full"


def test_radius_class_returns_empty_for_unknown():
    assert radius_class("absurd") == ""
    assert radius_class(None) == ""
