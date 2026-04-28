"""Tests for the notebook runtime: cell tracking, widget registry, re-execution."""

from __future__ import annotations

import pytest

from reflex.notebook.runtime import NotebookRuntime, get_runtime


def test_get_runtime_is_singleton():
    rt1 = get_runtime()
    rt2 = get_runtime()
    assert rt1 is rt2


def test_record_cell_appends_in_execution_order():
    rt = NotebookRuntime()
    rt.record_cell("a = 1", cell_id="c1")
    rt.record_cell("b = 2", cell_id="c2")
    rt.record_cell("c = 3", cell_id="c3")
    assert [c.cell_id for c in rt.cells] == ["c1", "c2", "c3"]
    assert [c.position for c in rt.cells] == [0, 1, 2]


def test_record_cell_updates_existing_in_place():
    rt = NotebookRuntime()
    rt.record_cell("a = 1", cell_id="c1")
    rt.record_cell("b = 2", cell_id="c2")
    rt.record_cell("a = 99", cell_id="c1")
    cells = rt.cells
    assert [c.cell_id for c in cells] == ["c2", "c1"]
    assert cells[-1].source == "a = 99"


def test_register_widget_tracks_cell_position():
    rt = NotebookRuntime()
    rt.record_cell("x", cell_id="c1")
    key = rt.next_widget_key("select")
    record = rt.register_widget(key=key, kind="select", label="X", value="A")
    assert record.cell_position == 0
    rt.record_cell("y", cell_id="c2")
    key2 = rt.next_widget_key("select")
    record2 = rt.register_widget(key=key2, kind="select", label="Y", value="B")
    assert record2.cell_position == 1


def test_next_widget_key_is_unique_per_call():
    rt = NotebookRuntime()
    rt.record_cell("x", cell_id="c1")
    k1 = rt.next_widget_key("select")
    k2 = rt.next_widget_key("select")
    assert k1 != k2


def test_register_widget_is_idempotent():
    rt = NotebookRuntime()
    rt.record_cell("x", cell_id="c1")
    key = rt.next_widget_key("select")
    a = rt.register_widget(key=key, kind="select", label="X", value="A")
    b = rt.register_widget(key=key, kind="select", label="X-updated", value="B")
    assert a is b
    assert rt._widgets[key].label == "X-updated"


def test_update_widget_value_triggers_rerun_via_fake_ipython():
    rt = NotebookRuntime()

    class FakeIPython:
        def __init__(self) -> None:
            self.run_history: list[str] = []
            self.events = type(
                "E",
                (),
                {
                    "register": lambda *_a, **_k: None,
                    "unregister": lambda *_a, **_k: None,
                },
            )()

        def run_cell(self, source: str, **_: object) -> None:
            self.run_history.append(source)

    fake = FakeIPython()
    rt._ipython = fake
    rt._installed = True
    rt.record_cell("widget cell", cell_id="c1")
    key = rt.next_widget_key("select")
    rt.register_widget(key=key, kind="select", label="X", value="A")
    rt.record_cell("downstream 1", cell_id="c2")
    rt.record_cell("downstream 2", cell_id="c3")
    rt.update_widget_value(key, "B")
    assert fake.run_history == ["widget cell", "downstream 1", "downstream 2"]


def test_rerun_restores_cell_context_for_widget_keys():
    rt = NotebookRuntime()
    captured: list[str] = []

    class FakeIPython:
        events = type("E", (), {"register": lambda *_a, **_k: None})()

        def run_cell(self, _source: str, **_: object) -> None:
            captured.append(rt.next_widget_key("select"))

    rt._ipython = FakeIPython()
    rt._installed = True
    rt.record_cell("c1 body", cell_id="c1")
    key = rt.next_widget_key("select")
    rt.register_widget(key=key, kind="select", label="X", value="A")
    rt.record_cell("c2 body", cell_id="c2")
    rt.record_cell("c3 body", cell_id="c3")
    rt.update_widget_value(key, "B")
    assert captured == ["c1:0:select", "c2:0:select", "c3:0:select"]


def test_update_widget_value_noop_when_unchanged():
    rt = NotebookRuntime()
    rt.record_cell("c", cell_id="c1")
    key = rt.next_widget_key("select")
    rt.register_widget(key=key, kind="select", label="X", value="A")
    fake_ran: list[str] = []

    class FakeIPython:
        events = type("E", (), {"register": lambda *_a, **_k: None})()

        def run_cell(self, source: str, **_: object) -> None:
            fake_ran.append(source)

    rt._ipython = FakeIPython()
    rt._installed = True
    rt.update_widget_value(key, "A")
    assert fake_ran == []


def test_update_widget_value_does_not_recurse():
    rt = NotebookRuntime()

    class FakeIPython:
        events = type("E", (), {"register": lambda *_a, **_k: None})()

        def __init__(self) -> None:
            self.calls = 0

        def run_cell(self, source: str, **_: object) -> None:
            self.calls += 1
            rt.update_widget_value("k", "C")

    rt._ipython = FakeIPython()
    rt._installed = True
    rt.record_cell("c1", cell_id="c1")
    rt.register_widget(key="k", kind="select", label="X", value="A")
    rt.record_cell("downstream", cell_id="c2")
    rt.update_widget_value("k", "B")
    assert rt._ipython.calls == 2


def test_record_output_attaches_to_current_cell():
    rt = NotebookRuntime()
    rt.record_cell("c", cell_id="c1")
    rt.record_output(kind="dataframe", repr_hint="DataFrame((10,3))")
    rt.record_cell("c2", cell_id="c2")
    rt.record_output(kind="primitive", repr_hint="int")
    outputs = rt.outputs
    assert [o.kind for o in outputs] == ["dataframe", "primitive"]
    assert [o.cell_position for o in outputs] == [0, 1]


def test_install_returns_false_outside_ipython():
    rt = NotebookRuntime()
    assert rt.install() is False
    assert rt.installed is False


def test_install_with_explicit_shell():
    class FakeShell:
        def __init__(self) -> None:
            self.registered: list[str] = []
            self.events = self

        def register(self, name: str, _cb: object) -> None:
            self.registered.append(name)

        def unregister(self, name: str, _cb: object) -> None:
            self.registered.remove(name)

    rt = NotebookRuntime()
    shell = FakeShell()
    assert rt.install(ipython=shell) is True
    assert "pre_run_cell" in shell.registered
    assert "post_run_cell" in shell.registered
    rt.uninstall()
    assert shell.registered == []


def test_reset_clears_all_recorded_state():
    rt = NotebookRuntime()
    rt.record_cell("c", cell_id="c1")
    rt.next_widget_key("select")
    rt.register_widget(key="k", kind="select", label="X", value="A")
    rt.record_output(kind="primitive", repr_hint="int")
    rt.reset()
    assert rt.cells == []
    assert rt.widgets == []
    assert rt.outputs == []


@pytest.mark.parametrize(
    "kind",
    [
        "select",
        "slider",
        "text_input",
        "checkbox",
        "date_picker",
        "file_upload",
        "button",
    ],
)
def test_widget_kinds_register_with_runtime(kind: str):
    rt = NotebookRuntime()
    rt.record_cell("c", cell_id="c1")
    key = rt.next_widget_key(kind)
    rt.register_widget(key=key, kind=kind, label="L", value=None)
    assert rt._widgets[key].kind == kind


def test_pre_run_cell_event_records_source():
    class FakeInfo:
        raw_cell = "x = 1"
        cell_id = "abc"

    rt = NotebookRuntime()
    rt._on_pre_run_cell(FakeInfo())
    assert rt.cells[0].source == "x = 1"
    assert rt.cells[0].cell_id == "abc"
