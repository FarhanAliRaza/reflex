"""Runtime that tracks notebook cells, registers widgets, and re-executes downstream cells on input change.

This is the heart of Reflex Notebooks. It hooks into the IPython kernel via ``pre_run_cell`` /
``post_run_cell`` events, builds an ordered log of executed cells, and exposes a registration
API for input widgets. When an input value changes, all cells that ran *after* the cell which
created the widget are re-executed against the latest value (the same model Streamlit uses).

The runtime degrades gracefully when running outside IPython: cell tracking is skipped, widgets
hold their default value, and code generation still works from any sources passed in explicitly.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CellRecord:
    """A single cell execution captured by the runtime."""

    cell_id: str
    source: str
    position: int


@dataclass
class WidgetRecord:
    """A registered input widget."""

    key: str
    kind: str
    label: str
    value: Any
    options: dict[str, Any]
    cell_position: int
    on_change: Callable[[Any], None] | None = None
    handle: Any = None


@dataclass
class OutputRecord:
    """An output produced by a cell (used for code generation)."""

    cell_position: int
    kind: str
    repr_hint: str


class NotebookRuntime:
    """Tracks cell execution, widget registry, and re-execution scheduling."""

    def __init__(self) -> None:
        """Create an uninitialized runtime."""
        self._cells: dict[str, CellRecord] = {}
        self._cell_order: list[str] = []
        self._widgets: dict[str, WidgetRecord] = {}
        self._outputs: list[OutputRecord] = []
        self._current_cell_id: str | None = None
        self._in_cell_counter: int = 0
        self._executing_widget_change: bool = False
        self._installed: bool = False
        self._ipython: Any = None
        self._lock = threading.RLock()

    @property
    def installed(self) -> bool:
        """Whether the runtime hooks have been installed in an IPython kernel."""
        return self._installed

    @property
    def cells(self) -> list[CellRecord]:
        """All recorded cells in execution order."""
        return [self._cells[cid] for cid in self._cell_order if cid in self._cells]

    @property
    def widgets(self) -> list[WidgetRecord]:
        """All registered widgets, sorted by their owning cell position."""
        return sorted(self._widgets.values(), key=lambda w: w.cell_position)

    @property
    def outputs(self) -> list[OutputRecord]:
        """All recorded outputs."""
        return list(self._outputs)

    def install(self, ipython: Any | None = None) -> bool:
        """Install IPython event hooks if available.

        Args:
            ipython: An IPython InteractiveShell instance, or None to auto-detect.

        Returns:
            True if hooks were installed, False if no IPython kernel was found.
        """
        if self._installed:
            return True
        shell = ipython if ipython is not None else _maybe_get_ipython()
        if shell is None:
            return False
        shell.events.register("pre_run_cell", self._on_pre_run_cell)
        shell.events.register("post_run_cell", self._on_post_run_cell)
        self._ipython = shell
        self._installed = True
        return True

    def uninstall(self) -> None:
        """Remove IPython event hooks (no-op if not installed)."""
        if not self._installed or self._ipython is None:
            return
        try:
            self._ipython.events.unregister("pre_run_cell", self._on_pre_run_cell)
            self._ipython.events.unregister("post_run_cell", self._on_post_run_cell)
        except ValueError:
            pass
        self._installed = False
        self._ipython = None

    def reset(self) -> None:
        """Clear all recorded state. Hooks remain installed."""
        with self._lock:
            self._cells.clear()
            self._cell_order.clear()
            self._widgets.clear()
            self._outputs.clear()
            self._current_cell_id = None
            self._in_cell_counter = 0

    def record_cell(self, source: str, cell_id: str | None = None) -> CellRecord:
        """Record a cell execution explicitly (used in non-IPython environments and tests).

        Args:
            source: The source code of the cell.
            cell_id: Optional stable ID for the cell. If omitted, a fresh UUID is used.

        Returns:
            The CellRecord for the newly recorded cell.
        """
        cid = cell_id or f"cell-{uuid.uuid4().hex[:8]}"
        with self._lock:
            if cid in self._cells:
                self._cell_order.remove(cid)
            position = len(self._cell_order)
            record = CellRecord(cell_id=cid, source=source, position=position)
            self._cells[cid] = record
            self._cell_order.append(cid)
            self._current_cell_id = cid
            self._in_cell_counter = 0
        return record

    def next_widget_key(self, kind: str) -> str:
        """Mint a stable key for a widget call inside the current cell.

        Args:
            kind: The widget kind (e.g. "select", "slider").

        Returns:
            A key unique to (current cell, in-cell index, kind).
        """
        cell_id = self._current_cell_id or "no-cell"
        index = self._in_cell_counter
        self._in_cell_counter += 1
        return f"{cell_id}:{index}:{kind}"

    def register_widget(
        self,
        key: str,
        kind: str,
        label: str,
        value: Any,
        options: dict[str, Any] | None = None,
        on_change: Callable[[Any], None] | None = None,
        handle: Any = None,
    ) -> WidgetRecord:
        """Register or update a widget for the current cell.

        Args:
            key: The widget's stable key (typically from ``next_widget_key``).
            kind: The widget kind (e.g. "select").
            label: Human-readable label.
            value: Current value of the widget.
            options: Extra options describing the widget (e.g. choices, min, max).
            on_change: Callback invoked when the widget's value changes.
            handle: Backing implementation handle (e.g. an ipywidgets widget).

        Returns:
            The WidgetRecord stored in the runtime.
        """
        with self._lock:
            existing = self._widgets.get(key)
            if existing is not None:
                existing.label = label
                existing.options = options or {}
                if on_change is not None:
                    existing.on_change = on_change
                if handle is not None:
                    existing.handle = handle
                return existing
            position = (
                self._cells[self._current_cell_id].position
                if self._current_cell_id and self._current_cell_id in self._cells
                else len(self._cell_order)
            )
            record = WidgetRecord(
                key=key,
                kind=kind,
                label=label,
                value=value,
                options=options or {},
                cell_position=position,
                on_change=on_change,
                handle=handle,
            )
            self._widgets[key] = record
            return record

    def update_widget_value(self, key: str, value: Any) -> None:
        """Update a widget's value and re-execute the widget's cell plus all downstream cells.

        Args:
            key: The widget's stable key.
            value: The new value.
        """
        with self._lock:
            record = self._widgets.get(key)
            if record is None or record.value == value:
                return
            record.value = value
            if self._executing_widget_change:
                return
            position = record.cell_position
        self._rerun_from(position)

    def record_output(self, kind: str, repr_hint: str = "") -> None:
        """Record an output produced by the current cell.

        Args:
            kind: A descriptive kind such as "dataframe" or "plotly".
            repr_hint: Short string used by codegen to identify the output.
        """
        if self._current_cell_id is None:
            return
        cell = self._cells[self._current_cell_id]
        self._outputs.append(
            OutputRecord(cell_position=cell.position, kind=kind, repr_hint=repr_hint)
        )

    def cells_after(self, position: int) -> list[CellRecord]:
        """Return all cells whose position is strictly greater than the given one.

        Args:
            position: The reference cell position.

        Returns:
            Cells executed after the reference cell, ordered by position.
        """
        return [c for c in self.cells if c.position > position]

    def cells_from(self, position: int) -> list[CellRecord]:
        """Return all cells whose position is greater than or equal to the given one.

        Args:
            position: The reference cell position.

        Returns:
            Cells starting at the reference cell, ordered by position.
        """
        return [c for c in self.cells if c.position >= position]

    def _rerun_from(self, position: int) -> None:
        """Re-execute the cell at ``position`` and every cell after it via IPython.

        While re-executing we restore ``_current_cell_id`` and ``_in_cell_counter`` for each
        cell so widget keys stay stable; ``_executing_widget_change`` suppresses the normal
        pre_run_cell hook and prevents recursive re-runs.

        Args:
            position: The position of the first cell to re-execute.
        """
        if self._ipython is None:
            return
        cells = self.cells_from(position)
        if not cells:
            return
        previous_cell_id = self._current_cell_id
        previous_counter = self._in_cell_counter
        self._executing_widget_change = True
        try:
            for cell in cells:
                self._current_cell_id = cell.cell_id
                self._in_cell_counter = 0
                self._ipython.run_cell(cell.source, store_history=False, silent=False)
        finally:
            self._executing_widget_change = False
            self._current_cell_id = previous_cell_id
            self._in_cell_counter = previous_counter

    def _on_pre_run_cell(self, info: Any) -> None:
        """IPython pre_run_cell event handler."""
        if self._executing_widget_change:
            return
        source = getattr(info, "raw_cell", "") or ""
        cell_id = getattr(info, "cell_id", None) or f"exec-{uuid.uuid4().hex[:8]}"
        self.record_cell(source=source, cell_id=cell_id)

    def _on_post_run_cell(self, result: Any) -> None:
        """IPython post_run_cell event handler."""
        return


_runtime: NotebookRuntime | None = None


def get_runtime() -> NotebookRuntime:
    """Return the process-wide notebook runtime, creating it on first use."""
    global _runtime
    if _runtime is None:
        _runtime = NotebookRuntime()
    return _runtime


def reset_runtime() -> None:
    """Reset the process-wide runtime (used by tests)."""
    global _runtime
    if _runtime is not None:
        _runtime.uninstall()
    _runtime = NotebookRuntime()


def _maybe_get_ipython() -> Any | None:
    """Return the active IPython InteractiveShell or None.

    Returns:
        The active IPython shell when running inside a Jupyter / IPython kernel, otherwise None.
    """
    try:
        from IPython import get_ipython  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None
    return get_ipython()
