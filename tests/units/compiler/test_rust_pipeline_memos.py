"""``@rx.memo`` component emission in the Rust pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("reflex_compiler_rust._native")

import reflex as rx
from reflex.compiler import rust_pipeline
from reflex.compiler import utils as compiler_utils
from reflex.compiler.session import CompilerSession


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty project dir as cwd so ``.web`` outputs land under tmp.

    Args:
        tmp_path: pytest tmp dir.
        monkeypatch: used to chdir into it.

    Returns:
        The project root.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@rx.memo
def memo_emission_probe(text: rx.Var[str]) -> rx.Component:
    """A module-level rx.memo component for the emission test.

    Args:
        text: The text to display.

    Returns:
        The component.
    """
    return rx.text(text)


class _MemoState(rx.State):
    label: str = "x"

    def bump(self):
        """No-op handler for the event-shape memo."""


@rx.memo
def memo_with_state_and_events(text: rx.Var[str]) -> rx.Component:
    """Memo exercising state vars, event chains, and control flow.

    Args:
        text: A prop rendered next to state.

    Returns:
        The component.
    """
    return rx.box(
        rx.text(text),
        rx.text(_MemoState.label),
        rx.el.button("go", on_click=_MemoState.bump),
        rx.cond(_MemoState.label, rx.text("yes"), rx.text("no")),
        rx.foreach(_MemoState.label.split(), rx.text),
        id="memo-anchor",
    )


@rx.memo
def memo_with_children(children: rx.Var[rx.Component]) -> rx.Component:
    """Memo with a children passthrough param.

    Args:
        children: The wrapped children.

    Returns:
        The component.
    """
    return rx.box(children, class_name="wrap")


@pytest.mark.parametrize(
    "memo_fn",
    [memo_emission_probe, memo_with_state_and_events, memo_with_children],
)
def test_arena_memo_module_matches_legacy_bytes(project: Path, memo_fn):
    """The arena rx.memo emitter is byte-identical to the legacy compiler.

    The legacy ``_compile_memo_components`` output is the oracle: the Rust
    path (one freeze + Rust module assembly + the ``_format_memo_imports``
    header) must produce the same bytes for the same definition.
    """
    from reflex.compiler.compiler import _compile_memo_components

    definition = memo_fn._definition
    legacy_files, _legacy_imports = _compile_memo_components([definition])
    (_legacy_path, legacy_code) = legacy_files[0]

    sess = CompilerSession()
    out_path = project / f"{definition.export_name}.jsx"
    sess.compile_rx_memo_arena(
        compiler_utils.prepare_memo_component_for_compile(definition),
        definition.export_name,
        compiler_utils.memo_component_signature(definition),
        str(out_path),
    )
    assert out_path.read_text() == legacy_code


def test_compile_pages_emits_rx_memo_files(project: Path):
    """``compile_pages`` writes one module per ``@rx.memo`` component.

    Regression: memo file emission lived only in the legacy compile, and
    ``run-rust``'s "one-shot" rebuild gate checked the removed
    ``utils/components.jsx`` — so the ~40s legacy compile ran on EVERY
    ``run-rust`` just to provide the ``$/utils/components/<Name>.jsx``
    modules that pages import.
    """

    def index():
        return rx.box(memo_emission_probe(text="hi"))

    app = rx.App()
    app.add_page(index, route="/")
    written, all_imports = rust_pipeline.compile_pages(app, session=CompilerSession())

    page_js = written["index"].read_text()
    assert "MemoEmissionProbe" in page_js
    memo_dir = Path(compiler_utils.get_memo_components_dir())
    memo_files = list(memo_dir.glob("MemoEmissionProbe*.jsx"))
    assert memo_files, sorted(memo_dir.glob("*"))
    assert "memo(" in memo_files[0].read_text()
    # The memo module's dependencies join the bun-install set.
    assert "react" in all_imports
