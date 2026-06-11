"""Differential tests for the Rust `format_as_emotion` port.

The freeze pass transforms `self.style` to the emotion CSS-in-JS shape in
Rust (base `_get_style` path only). Every case here asserts the compiled
page embeds exactly the bytes the Python reference —
``LiteralVar.create(format_as_emotion(component.style))`` — would produce,
covering pseudo-selectors, breakpoints (named, custom, dict-valued),
responsive lists (incl. merge into shared media queries), raw nested
dicts, CSS vars, Vars, and empty nested dicts.
"""

from __future__ import annotations

import pytest

pytest.importorskip("reflex_compiler_rust._native")

from reflex_base.breakpoints import Breakpoints
from reflex_base.style import format_as_emotion
from reflex_base.vars.base import LiteralVar

import reflex as rx
from reflex.compiler.session import CompilerSession

CASES = {
    "bp_named": {"color": Breakpoints.create(initial="red", sm="blue", lg="green")},
    "bp_custom": {
        "color": Breakpoints.create(custom={"500px": "red", "900px": "blue"})
    },
    "bp_dict_values": {
        "_hover": Breakpoints.create(initial={"color": "red"}, md={"color": "blue"})
    },
    "colon_keys": {":hover": {"color": "red"}, "::before": {"content": '"x"'}},
    "multiword_pseudo": {
        "_focusWithin": {"outline": "1px"},
        "_firstChild": {"margin": "0"},
    },
    "raw_nested": {"& .child": {"color": "blue", "padding": ["1px", "2px"]}},
    "css_vars": {"--my-var": "10px", "color": "var(--my-var)"},
    "list_merge": {"width": ["1px", "2px", "3px"], "height": ["4px", "5px"]},
    "list_in_pseudo": {"_hover": {"color": ["red", "blue"]}},
    "var_value": {
        "background": rx.color("accent", 5),
        "_active": {"color": rx.color("red", 9)},
    },
    "empty_nested": {"& .x": {}},
    "mixed": {
        "padding_x": "4px",
        "fontSize": "2em",
        "_hover": {"transform": "scale(1.1)", "_before": {"content": '"*"'}},
    },
}


@pytest.fixture(scope="module")
def session() -> CompilerSession:
    return CompilerSession()


@pytest.mark.parametrize("name", CASES, ids=list(CASES))
def test_rust_emotion_matches_python_reference(name: str, session: CompilerSession):
    """The compiled css expression is byte-identical to the Python path.

    Args:
        name: Key into ``CASES`` selecting the style dict under test.
        session: Module-scoped compiler session.
    """
    style = CASES[name]
    expected = str(
        LiteralVar.create(format_as_emotion(rx.el.div("t", style=style).style))
    )
    page_js, _bodies, _imports, *_ = session.compile_page_from_component_arena(
        rx.el.div("t", style=style), f"Style{name.title()}", f"/style_{name}"
    )
    assert f"css: {expected}" in page_js
