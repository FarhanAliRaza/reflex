"""Regression tests for ``reflex_components_radix._variants.cn``.

The earlier implementation called ``p == ""`` and ``p == []`` on every
fragment, which raised ``VarTypeError`` when the docs site passed a
class-name composed from ``rx.cond`` (a Var). These tests pin the
behavior so that path stays open.
"""

from reflex_base.vars.base import LiteralVar, Var
from reflex_components_core.core.cond import cond
from reflex_components_radix._variants import cn


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
        LiteralVar.create(True), "x", "y",
    )
    out = cn("prefix", var_class)
    assert isinstance(out, list)
    assert out[0] == "prefix"
    assert isinstance(out[1], Var)
