"""Tests for the output dispatcher."""

from __future__ import annotations

import math

import pytest

from reflex.notebook import outputs
from reflex.notebook.runtime import get_runtime


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        (1, "primitive"),
        ("hello", "primitive"),
        (math.pi, "primitive"),
        (True, "primitive"),
        (None, "primitive"),
    ],
)
def test_classify_primitives(value: object, kind: str) -> None:
    assert outputs.classify(value)[0] == kind


def test_classify_html_repr():
    class WithHtml:
        def _repr_html_(self) -> str:
            return "<b>x</b>"

    assert outputs.classify(WithHtml())[0] == "html"


def test_classify_unknown():
    class Foo:
        pass

    assert outputs.classify(Foo())[0] == "unknown"


def test_classify_pandas_dataframe_module_path():
    class FakeDataFrame:
        shape = (3, 2)

    FakeDataFrame.__module__ = "pandas.core.frame"
    FakeDataFrame.__name__ = "DataFrame"
    assert outputs.classify(FakeDataFrame())[0] == "dataframe"


def test_classify_matplotlib_figure_module_path():
    class FakeFigure:
        pass

    FakeFigure.__module__ = "matplotlib.figure"
    FakeFigure.__name__ = "Figure"
    assert outputs.classify(FakeFigure())[0] == "matplotlib"


def test_classify_plotly_figure_module_path():
    class FakeFigure:
        pass

    FakeFigure.__module__ = "plotly.graph_objs._figure"
    FakeFigure.__name__ = "Figure"
    assert outputs.classify(FakeFigure())[0] == "plotly"


def test_display_records_output_on_runtime():
    rt = get_runtime()
    rt.record_cell("c", cell_id="c1")
    outputs.display(42)
    outputs.display("hi")
    assert [o.kind for o in rt.outputs] == ["primitive", "primitive"]
    assert all(o.cell_position == 0 for o in rt.outputs)


def test_display_returns_input():
    get_runtime().record_cell("c")
    payload = {"a": 1}
    assert outputs.display(payload) is payload
