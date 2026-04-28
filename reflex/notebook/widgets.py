"""Input widgets for Reflex Notebooks.

The seven Phase 1 primitives: ``select``, ``slider``, ``text_input``, ``checkbox``,
``date_picker``, ``file_upload``, and ``button``.

Each function follows the Streamlit pattern: when called inside a notebook cell it both
displays an interactive widget and returns the widget's current value. The widget is keyed
to the cell so that re-execution reuses the user's selection. When ipywidgets is not
installed (or we are not in IPython) the call simply returns the default value, which keeps
``view_source`` and ``deploy`` working in any environment.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Sequence
from typing import Any

from reflex.notebook.runtime import get_runtime


def _try_import_ipywidgets() -> Any | None:
    try:
        import ipywidgets  # type: ignore[import-not-found]
    except ImportError:
        return None
    return ipywidgets


def _try_import_display() -> Callable[[Any], None] | None:
    try:
        from IPython.display import display  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None
    return display


def _bind(record_value_setter: Callable[[Any], None], handle: Any) -> None:
    """Connect an ipywidgets value-change observation to a setter."""
    if handle is None:
        return

    def _observer(change: Any) -> None:
        record_value_setter(change.get("new"))

    handle.observe(_observer, names="value")


def select(
    options: Sequence[Any],
    default: Any | None = None,
    *,
    label: str = "",
) -> Any:
    """Render a dropdown and return the currently selected value.

    Args:
        options: The choices to offer.
        default: Initial value. Defaults to the first option.
        label: A human-readable label rendered next to the widget.

    Returns:
        The currently selected option.
    """
    if not options:
        msg = "select() requires at least one option"
        raise ValueError(msg)
    runtime = get_runtime()
    key = runtime.next_widget_key("select")
    existing = runtime._widgets.get(key)
    initial = (
        existing.value
        if existing is not None
        else (default if default is not None else options[0])
    )
    if initial not in options:
        initial = options[0]
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else ipw.Dropdown(options=list(options), value=initial, description=label)
        )
        handle.options = list(options)
        handle.value = initial
        _bind(lambda v: runtime.update_widget_value(key, v), handle)
    record = runtime.register_widget(
        key=key,
        kind="select",
        label=label,
        value=initial,
        options={"choices": list(options)},
        handle=handle,
    )
    _maybe_display(handle)
    return record.value


def slider(
    min: float = 0,
    max: float = 100,
    default: float | None = None,
    step: float = 1,
    *,
    label: str = "",
) -> float:
    """Render a slider and return the current numeric value.

    Args:
        min: Minimum value.
        max: Maximum value.
        default: Initial value. Defaults to ``min``.
        step: Increment between values.
        label: A human-readable label rendered next to the widget.

    Returns:
        The current slider value.
    """
    if max < min:
        msg = "slider() requires max >= min"
        raise ValueError(msg)
    runtime = get_runtime()
    key = runtime.next_widget_key("slider")
    existing = runtime._widgets.get(key)
    initial = (
        existing.value
        if existing is not None
        else (default if default is not None else min)
    )
    initial = _clamp(initial, min, max)
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        cls = (
            ipw.FloatSlider
            if isinstance(step, float) and not float(step).is_integer()
            else ipw.IntSlider
        )
        if cls is ipw.IntSlider:
            initial = int(initial)
            min = int(min)
            max = int(max)
            step = int(step) or 1
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else cls(min=min, max=max, value=initial, step=step, description=label)
        )
        handle.min = min
        handle.max = max
        handle.step = step
        handle.value = initial
        _bind(lambda v: runtime.update_widget_value(key, v), handle)
    record = runtime.register_widget(
        key=key,
        kind="slider",
        label=label,
        value=initial,
        options={"min": min, "max": max, "step": step},
        handle=handle,
    )
    _maybe_display(handle)
    return record.value


def text_input(
    default: str = "",
    *,
    label: str = "",
    placeholder: str = "",
) -> str:
    """Render a single-line text input and return its current value.

    Args:
        default: Initial value.
        label: A human-readable label rendered next to the widget.
        placeholder: Placeholder text shown when the input is empty.

    Returns:
        The current text value.
    """
    runtime = get_runtime()
    key = runtime.next_widget_key("text_input")
    existing = runtime._widgets.get(key)
    initial = existing.value if existing is not None else default
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else ipw.Text(value=initial, description=label, placeholder=placeholder)
        )
        handle.value = initial
        handle.placeholder = placeholder
        _bind(lambda v: runtime.update_widget_value(key, v), handle)
    record = runtime.register_widget(
        key=key,
        kind="text_input",
        label=label,
        value=initial,
        options={"placeholder": placeholder},
        handle=handle,
    )
    _maybe_display(handle)
    return record.value


def checkbox(default: bool = False, *, label: str = "") -> bool:
    """Render a checkbox and return its current boolean value.

    Args:
        default: Initial value.
        label: A human-readable label rendered next to the widget.

    Returns:
        The current checkbox state.
    """
    runtime = get_runtime()
    key = runtime.next_widget_key("checkbox")
    existing = runtime._widgets.get(key)
    initial = existing.value if existing is not None else default
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else ipw.Checkbox(value=initial, description=label)
        )
        handle.value = initial
        _bind(lambda v: runtime.update_widget_value(key, v), handle)
    record = runtime.register_widget(
        key=key,
        kind="checkbox",
        label=label,
        value=initial,
        options={},
        handle=handle,
    )
    _maybe_display(handle)
    return record.value


def date_picker(
    default: _dt.date | None = None,
    *,
    label: str = "",
) -> _dt.date:
    """Render a date picker and return the currently selected date.

    Args:
        default: Initial date. Defaults to today.
        label: A human-readable label rendered next to the widget.

    Returns:
        The currently selected ``datetime.date``.
    """
    runtime = get_runtime()
    key = runtime.next_widget_key("date_picker")
    existing = runtime._widgets.get(key)
    initial = (
        existing.value
        if existing is not None and existing.value is not None
        else (default if default is not None else _dt.date.today())
    )
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else ipw.DatePicker(value=initial, description=label)
        )
        handle.value = initial
        _bind(lambda v: runtime.update_widget_value(key, v), handle)
    record = runtime.register_widget(
        key=key,
        kind="date_picker",
        label=label,
        value=initial,
        options={},
        handle=handle,
    )
    _maybe_display(handle)
    return record.value


def file_upload(
    *,
    label: str = "Upload",
    accept: str = "",
) -> dict[str, Any] | None:
    """Render a file uploader and return the most recent uploaded file.

    Args:
        label: A human-readable label rendered next to the widget.
        accept: Comma-separated MIME types or extensions accepted (e.g. ``".csv"``).

    Returns:
        A dict with keys ``name``, ``size``, and ``content`` (bytes), or None if
        nothing has been uploaded yet.
    """
    runtime = get_runtime()
    key = runtime.next_widget_key("file_upload")
    existing = runtime._widgets.get(key)
    initial = existing.value if existing is not None else None
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else ipw.FileUpload(description=label, accept=accept, multiple=False)
        )

        def _on_upload(change: Any) -> None:
            new = change.get("new")
            if not new:
                runtime.update_widget_value(key, None)
                return
            entry = (
                new[0] if isinstance(new, (list, tuple)) else next(iter(new.values()))
            )
            payload = {
                "name": entry.get("name")
                if isinstance(entry, dict)
                else getattr(entry, "name", ""),
                "size": entry.get("size")
                if isinstance(entry, dict)
                else getattr(entry, "size", 0),
                "content": entry.get("content")
                if isinstance(entry, dict)
                else getattr(entry, "content", b""),
            }
            runtime.update_widget_value(key, payload)

        handle.observe(_on_upload, names="value")
    record = runtime.register_widget(
        key=key,
        kind="file_upload",
        label=label,
        value=initial,
        options={"accept": accept},
        handle=handle,
    )
    _maybe_display(handle)
    return record.value


def button(*, label: str = "Click") -> bool:
    """Render a button and return True for the single execution that follows a click.

    Args:
        label: The button label.

    Returns:
        True if the button was just clicked, False otherwise.
    """
    runtime = get_runtime()
    key = runtime.next_widget_key("button")
    existing = runtime._widgets.get(key)
    just_clicked = bool(existing and existing.options.get("_pending_click"))
    handle = None
    ipw = _try_import_ipywidgets()
    if ipw is not None:
        handle = (
            existing.handle
            if existing is not None and existing.handle is not None
            else ipw.Button(description=label)
        )
        handle.description = label

        def _on_click(_btn: Any) -> None:
            record = runtime._widgets.get(key)
            if record is not None:
                record.options["_pending_click"] = True
            runtime.update_widget_value(
                key, runtime._widgets[key].value + 1 if record else 1
            )

        handle.on_click(_on_click)
    record = runtime.register_widget(
        key=key,
        kind="button",
        label=label,
        value=existing.value if existing is not None else 0,
        options={"_pending_click": False},
        handle=handle,
    )
    if just_clicked:
        record.options["_pending_click"] = False
    _maybe_display(handle)
    return just_clicked


def _maybe_display(handle: Any) -> None:
    """Display a widget handle if we have an IPython display available."""
    if handle is None:
        return
    display = _try_import_display()
    if display is not None:
        display(handle)


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a numeric value into ``[lo, hi]``.

    Args:
        value: The input value.
        lo: The lower bound.
        hi: The upper bound.

    Returns:
        ``value`` constrained to the inclusive range ``[lo, hi]``.
    """
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
