"""Shared Var expression corpus + capture helpers (single source of truth).

Both ``scripts/capture_var_golden.py`` (which writes the golden file) and
``test_var_golden_parity.py`` (which gates against it) import this module, so
the oracle and the gate exercise byte-identical expressions.

It lives in a fixed module path on purpose: a state Var's rendered name embeds
the module its state class is defined in, so the corpus is only reproducible
if every consumer imports this module under the *same* dotted name
(``tests.units.vars._var_corpus``). Importing it as ``__main__`` or a bare
``_var_corpus`` would change every state expression's output.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import reflex as rx
from reflex.vars import LiteralVar, Var


class _GoldenState(rx.State):
    """A state whose fields seed every typed Var leaf used in the corpus."""

    count: int = 0
    ratio: float = 1.5
    name: str = "n"
    flag: bool = False
    items: list[int] = [1, 2, 3]
    words: list[str] = ["a", "b"]
    data: dict[str, int] = {"a": 1}


def _type_name(t: Any) -> str:
    """Render a var_type to a stable string.

    Args:
        t: The var type to render.

    Returns:
        A stable string name for the type.
    """
    if t is None:
        return "None"
    return getattr(t, "__name__", None) or str(t)


def _var_data_repr(v: Var) -> Any:
    """Normalize ``_get_all_var_data()`` to a JSON-stable structure.

    Captures the fields that matter for parity: state, field_name, hooks,
    deps, and a flattened (library, tag) view of imports.

    Args:
        v: The var whose aggregate var_data to capture.

    Returns:
        A JSON-stable dict, or None if the var carries no var_data.
    """
    vd = v._get_all_var_data()
    if vd is None:
        return None
    imports = sorted([lib, tag.tag] for lib, tags in vd.imports for tag in tags)
    return {
        "state": vd.state or None,
        "field_name": vd.field_name or None,
        "hooks": sorted(vd.hooks),
        "deps": sorted(d._js_expr for d in vd.deps),
        "imports": imports,
    }


def _record(v: Var) -> dict[str, Any]:
    """Freeze one Var's observable output.

    Args:
        v: The var to record.

    Returns:
        The var's js_expr, var_type name, and normalized var_data.
    """
    return {
        "js_expr": v._js_expr,
        "var_type": _type_name(v._var_type),
        "var_data": _var_data_repr(v),
    }


def _corpus() -> dict[str, Callable[[], Var]]:
    """The expression matrix. Keyed by stable id; each builds one Var.

    Returns:
        A mapping of expression id to a zero-arg builder for that Var.
    """
    s = _GoldenState
    return {
        # --- literals ---
        "lit_int": lambda: LiteralVar.create(5),
        "lit_neg_int": lambda: LiteralVar.create(-7),
        "lit_float": lambda: LiteralVar.create(1.5),
        "lit_str": lambda: LiteralVar.create("hi"),
        "lit_str_quote": lambda: LiteralVar.create('a"b'),
        "lit_bool_true": lambda: LiteralVar.create(True),
        "lit_bool_false": lambda: LiteralVar.create(False),
        "lit_none": lambda: LiteralVar.create(None),
        "lit_list": lambda: LiteralVar.create([1, 2, 3]),
        "lit_list_str": lambda: LiteralVar.create(["a", "b"]),
        "lit_nested_list": lambda: LiteralVar.create([[1, 2], [3]]),
        "lit_dict": lambda: LiteralVar.create({"a": 1, "b": 2}),
        "lit_dict_nested": lambda: LiteralVar.create({"a": {"b": 1}}),
        # --- raw base var ---
        "raw_var": lambda: Var(_js_expr="x", _var_type=int),
        # --- state leaves ---
        "state_int": lambda: s.count,
        "state_float": lambda: s.ratio,
        "state_str": lambda: s.name,
        "state_bool": lambda: s.flag,
        "state_list": lambda: s.items,
        "state_dict": lambda: s.data,
        # --- number operators ---
        "num_add": lambda: s.count + 1,
        "num_radd": lambda: 1 + s.count,
        "num_sub": lambda: s.count - 2,
        "num_rsub": lambda: 10 - s.count,
        "num_mul": lambda: s.count * 3,
        "num_truediv": lambda: s.count / 2,
        "num_floordiv": lambda: s.count // 2,
        "num_mod": lambda: s.count % 5,
        "num_pow": lambda: s.count**2,
        "num_neg": lambda: -s.count,
        "num_abs": lambda: abs(s.count),
        "num_gt": lambda: s.count > 0,
        "num_ge": lambda: s.count >= 1,
        "num_lt": lambda: s.count < 5,
        "num_le": lambda: s.count <= 5,
        "num_eq": lambda: s.count == 3,
        "num_ne": lambda: s.count != 3,
        "num_nested": lambda: (s.count + 1) * 2 > 4,
        "num_float_add": lambda: s.ratio + 0.5,
        # --- boolean operators ---
        "bool_and": lambda: s.flag & (s.count > 0),
        "bool_or": lambda: s.flag | (s.count > 0),
        "bool_invert": lambda: ~s.flag,
        # --- string operators / methods ---
        "str_add": lambda: s.name + "!",
        "str_radd": lambda: "hello " + s.name,
        "str_mul": lambda: s.name * 2,
        "str_lower": lambda: s.name.lower(),
        "str_upper": lambda: s.name.upper(),
        "str_capitalize": lambda: s.name.capitalize(),
        "str_length": lambda: s.name.length(),
        "str_contains": lambda: s.name.contains("a"),
        "str_startswith": lambda: s.name.startswith("a"),
        "str_split": lambda: s.name.split(","),
        "str_getitem": lambda: s.name[0],
        # --- array operators / methods ---
        "arr_length": lambda: s.items.length(),
        "arr_getitem": lambda: s.items[0],
        "arr_contains": lambda: s.items.contains(1),
        "arr_reverse": lambda: s.items.reverse(),
        "arr_join": lambda: s.words.join(","),
        "arr_concat": lambda: s.items + LiteralVar.create([4, 5]),
        # --- object operators / methods ---
        "obj_getitem": lambda: s.data["a"],
        "obj_getattr": lambda: s.data.a,
        "obj_keys": lambda: s.data.keys(),
        "obj_values": lambda: s.data.values(),
        "obj_contains": lambda: s.data.contains("a"),
        # --- casting ---
        "to_str": lambda: s.count.to(str),
        "to_int": lambda: Var(_js_expr="x").to(int),
        "to_bool": lambda: Var(_js_expr="x").to(bool),
        # --- f-strings / format ---
        "fstr_simple": lambda: LiteralVar.create(f"v={s.count}"),
        "fstr_multi": lambda: LiteralVar.create(f"{s.name}={s.count}"),
        "fstr_nested_op": lambda: LiteralVar.create(f"sum={s.count + 1}"),
    }
