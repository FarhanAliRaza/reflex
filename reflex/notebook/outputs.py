"""Output dispatch for Reflex Notebooks.

Five output kinds are supported in Phase 1:
    - pandas DataFrame
    - matplotlib figure
    - plotly figure
    - primitives (str/int/float/bool/None)
    - HTML / Markdown / objects with ``_repr_html_``

The dispatcher records each output on the runtime so that ``view_source`` and ``deploy`` can
generate a Reflex page that reproduces the cell layout. In a live notebook the dispatcher
also calls ``IPython.display.display`` so the user sees the value inline.
"""

from __future__ import annotations

from typing import Any

from reflex.notebook.runtime import get_runtime


def display(obj: Any) -> Any:
    """Display ``obj`` using the most specific renderer available and record it.

    Args:
        obj: The value to display. Pandas DataFrames, matplotlib figures, plotly figures,
            primitives, and any object exposing ``_repr_html_`` are recognized.

    Returns:
        The original object, so the function can be chained.
    """
    kind, repr_hint = classify(obj)
    runtime = get_runtime()
    runtime.record_output(kind=kind, repr_hint=repr_hint)
    _render(obj, kind)
    return obj


def classify(obj: Any) -> tuple[str, str]:
    """Classify an object into one of the supported output kinds.

    Args:
        obj: The value being displayed.

    Returns:
        A pair ``(kind, repr_hint)`` where ``kind`` is one of ``"primitive"``,
        ``"dataframe"``, ``"matplotlib"``, ``"plotly"``, ``"html"``, or ``"unknown"``,
        and ``repr_hint`` is a short string used by codegen.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return "primitive", type(obj).__name__
    if _is_pandas_dataframe(obj):
        return "dataframe", f"DataFrame({getattr(obj, 'shape', '?')})"
    if _is_matplotlib_figure(obj):
        return "matplotlib", "Figure"
    if _is_plotly_figure(obj):
        return "plotly", "plotly.Figure"
    if hasattr(obj, "_repr_html_"):
        return "html", type(obj).__name__
    return "unknown", type(obj).__name__


def _render(obj: Any, kind: str) -> None:
    """Render an object via IPython.display if available.

    Args:
        obj: The value to render.
        kind: The classified output kind.
    """
    try:
        from IPython.display import display as ip_display  # noqa: I001  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    if kind == "matplotlib":
        try:
            import matplotlib.pyplot as plt  # type: ignore[import-not-found]
        except ImportError:
            ip_display(obj)
            return
        ip_display(obj)
        plt.close(obj)
        return
    ip_display(obj)


def _is_pandas_dataframe(obj: Any) -> bool:
    """Check whether ``obj`` is a pandas DataFrame without importing pandas eagerly.

    Args:
        obj: The value to inspect.

    Returns:
        True if ``obj`` is a pandas DataFrame, False otherwise.
    """
    cls = type(obj)
    return cls.__module__.startswith("pandas.") and cls.__name__ == "DataFrame"


def _is_matplotlib_figure(obj: Any) -> bool:
    """Check whether ``obj`` is a matplotlib Figure without importing matplotlib eagerly.

    Args:
        obj: The value to inspect.

    Returns:
        True if ``obj`` is a matplotlib Figure, False otherwise.
    """
    cls = type(obj)
    return cls.__module__.startswith("matplotlib.") and cls.__name__ == "Figure"


def _is_plotly_figure(obj: Any) -> bool:
    """Check whether ``obj`` is a plotly figure without importing plotly eagerly.

    Args:
        obj: The value to inspect.

    Returns:
        True if ``obj`` is a plotly Figure / FigureWidget, False otherwise.
    """
    for klass in type(obj).__mro__:
        if klass.__module__.startswith("plotly.") and klass.__name__ in {
            "Figure",
            "FigureWidget",
        }:
            return True
    return False
