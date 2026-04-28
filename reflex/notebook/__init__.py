"""Reflex Notebooks: turn any Jupyter notebook into a deployed Reflex app in three lines of Python.

Usage::

    import reflex as rx
    rx.notebook()                       # initialize once at the top of the notebook
    df = pd.read_csv("data.csv")
    category = rx.notebook.select(sorted(df["category"].unique()), label="Category")
    df[df["category"] == category]      # any normal cell output is captured
    rx.notebook.deploy("my_app")        # generate a Reflex app and print the run command

The seven Phase 1 input primitives (``select``, ``slider``, ``text_input``, ``checkbox``,
``date_picker``, ``file_upload``, ``button``) all live on this module, alongside ``row``
for horizontal layout, ``display`` for explicit output dispatch, ``view_source`` for
inspecting the generated Reflex code, and ``deploy`` for materializing the app on disk.
"""

from __future__ import annotations

import sys as _sys
import types as _types
from typing import Any

from reflex.notebook.codegen import generate_app_source
from reflex.notebook.deploy import deploy
from reflex.notebook.layout import row
from reflex.notebook.outputs import display
from reflex.notebook.runtime import (
    CellRecord,
    NotebookRuntime,
    OutputRecord,
    WidgetRecord,
    get_runtime,
    reset_runtime,
)
from reflex.notebook.widgets import (
    button,
    checkbox,
    date_picker,
    file_upload,
    select,
    slider,
    text_input,
)

__all__ = [
    "CellRecord",
    "NotebookRuntime",
    "OutputRecord",
    "WidgetRecord",
    "button",
    "checkbox",
    "date_picker",
    "deploy",
    "display",
    "file_upload",
    "generate_app_source",
    "get_runtime",
    "init",
    "reset_runtime",
    "row",
    "select",
    "slider",
    "text_input",
    "view_source",
]


def init(*, ipython: Any | None = None, reset: bool = False) -> NotebookRuntime:
    """Initialize the notebook runtime and install IPython hooks if available.

    Args:
        ipython: An optional IPython InteractiveShell instance to attach to.
        reset: If True, discard any previously recorded state.

    Returns:
        The active runtime.
    """
    if reset:
        reset_runtime()
    runtime = get_runtime()
    runtime.install(ipython=ipython)
    return runtime


def view_source(app_name: str = "notebook_app", *, print_source: bool = True) -> str:
    """Return (and optionally print) the Reflex source generated from the current runtime.

    Args:
        app_name: The slug used in the generated app's title.
        print_source: When True (the default), also print the source to stdout.

    Returns:
        The generated Reflex source as a string.
    """
    source = generate_app_source(get_runtime(), app_name=app_name)
    if print_source:
        print(source)  # noqa: T201
    return source


class _CallableNotebookModule(_types.ModuleType):
    """Module subclass that lets ``rx.notebook(...)`` work as shorthand for ``rx.notebook.init(...)``."""

    def __call__(self, *args: Any, **kwargs: Any) -> NotebookRuntime:
        """Forward calls on the module itself to ``init``.

        Args:
            *args: Positional arguments forwarded to :func:`init`.
            **kwargs: Keyword arguments forwarded to :func:`init`.

        Returns:
            The active runtime.
        """
        return init(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableNotebookModule
