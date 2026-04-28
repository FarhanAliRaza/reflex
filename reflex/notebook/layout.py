"""Layout helpers for Reflex Notebooks.

Phase 1 only ships ``row``: anything else stacks vertically by default. ``row`` accepts
already-rendered values and emits a horizontal box in IPython, while recording the layout
so codegen can emit ``rx.hstack`` for the deployed Reflex app.
"""

from __future__ import annotations

from typing import Any

from reflex.notebook.outputs import classify
from reflex.notebook.runtime import get_runtime


def row(*items: Any) -> tuple[Any, ...]:
    """Display ``items`` in a horizontal row and record the layout.

    Args:
        *items: The values to render side by side.

    Returns:
        The items, unchanged, so callers can chain.
    """
    runtime = get_runtime()
    kinds = [classify(item)[0] for item in items]
    runtime.record_output(kind="row", repr_hint=",".join(kinds))
    _render_row(items)
    return items


def _render_row(items: tuple[Any, ...]) -> None:
    """Render items horizontally if ipywidgets is available, otherwise fall back to display.

    Args:
        items: The values to render side by side.
    """
    try:
        import ipywidgets  # type: ignore[import-not-found]
        from IPython.display import display  # pyright: ignore[reportMissingImports]
    except ImportError:
        try:
            from IPython.display import display  # pyright: ignore[reportMissingImports]
        except ImportError:
            return
        for item in items:
            display(item)
        return
    children = []
    for item in items:
        if isinstance(item, ipywidgets.Widget):
            children.append(item)
            continue
        out = ipywidgets.Output()
        with out:
            display(item)
        children.append(out)
    display(ipywidgets.HBox(children))
