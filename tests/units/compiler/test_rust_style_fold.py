"""M2 gate: the deferred (in-freeze) style fold is byte-identical.

Each fixture compiles twice through the real pipeline pieces:

* legacy: ``compile_unevaluated_page(apply_style=True)`` runs the Python
  ``_add_style_recursive`` walk, then the freeze sees pre-folded styles.
* deferred: ``compile_unevaluated_page(apply_style=False)`` marks the fold
  root; the freeze applies ``_apply_style_fold`` per node under the mark,
  driven by the ``app_style`` dict passed to the arena entry.

The page JS, memo bodies, and harvested imports must match exactly.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from reflex_base.breakpoints import Breakpoints
from reflex_base.components.component import Component
from reflex_base.utils.imports import ImportVar
from reflex_base.vars.base import Var, VarData

import reflex as rx
from reflex.app import UnevaluatedPage
from reflex.compiler.compiler import compile_unevaluated_page
from reflex.compiler.session import CompilerSession

pytest.importorskip("reflex_compiler_rust._native")


class AddStyleComp(Component):
    """Class-level default styles via the ``add_style`` API."""

    tag = "AddStyleComp"
    library = "style-fold-lib"

    def add_style(self):
        """Return the class's default style contribution.

        Returns:
            The default style dict.
        """
        return {"color": "red", "padding": "4px"}


class AddStyleSubComp(AddStyleComp):
    """Subclass adding its own layer on top of the parent's add_style."""

    tag = "AddStyleSubComp"

    def add_style(self):
        """Return the subclass's default style contribution.

        Returns:
            The default style dict.
        """
        return {"color": "blue", "margin": "2px"}


class PlainComp(Component):
    """No add_style chain — folds only via App.style entries."""

    tag = "PlainComp"
    library = "style-fold-lib"


_IMPORT_FIELDS = ("tag", "alias", "is_default", "install", "render", "package_path")


def _canon_imports(imports: dict) -> dict[str, list[str]]:
    # Field-wise serialization (same as parity_oracle): RustImportVar's
    # default repr carries a memory address. Deduped — entry multiplicity
    # depends on walk internals, not output semantics.
    return {
        lib: sorted({
            repr(tuple(getattr(iv, f, None) for f in _IMPORT_FIELDS)) for iv in ivs
        })
        for lib, ivs in sorted(imports.items())
    }


def _compile(
    build: Callable[[], Component],
    app_style: dict | None,
    *,
    deferred: bool,
) -> tuple[str, list, dict]:
    sess = CompilerSession()
    unev = UnevaluatedPage(component=build, route="/style-fold-diff")
    component = compile_unevaluated_page(
        "/style-fold-diff", unev, app_style, None, apply_style=not deferred
    )
    page_js, bodies, imports, _ = sess.compile_page_from_component_arena(
        component,
        "StyleFoldDiff",
        "style-fold-diff",
        app_style=(app_style if deferred else None),
    )
    return page_js, sorted(bodies), _canon_imports(imports)


def _assert_fold_parity(build: Callable[[], Component], app_style: dict | None):
    legacy_js, legacy_bodies, legacy_imports = _compile(
        build, app_style, deferred=False
    )
    fold_js, fold_bodies, fold_imports = _compile(build, app_style, deferred=True)
    assert fold_js == legacy_js
    assert fold_bodies == legacy_bodies
    assert fold_imports == legacy_imports
    return legacy_js


def test_plain_tree_no_app_style():
    js = _assert_fold_parity(
        lambda: rx.box(rx.text("hi", color="red"), rx.el.div("nested")), {}
    )
    assert "hi" in js


def test_add_style_chain_folds():
    js = _assert_fold_parity(
        lambda: rx.box(AddStyleComp.create(background_color="green")), {}
    )
    # The add_style default must appear in the emitted css.
    assert "red" in js
    assert "green" in js


def test_add_style_mro_chain_order():
    js = _assert_fold_parity(lambda: AddStyleSubComp.create(), {})
    # Subclass layer wins over parent (color blue beats red).
    assert "blue" in js


def test_app_style_entry_by_class():
    text_cls = type(rx.text("x"))
    js = _assert_fold_parity(
        lambda: rx.box(rx.text("styled"), PlainComp.create()),
        {text_cls: {"font_weight": "bold"}, PlainComp: {"color": "purple"}},
    )
    assert "bold" in js
    assert "purple" in js


def test_app_style_entry_by_create_method():
    js = _assert_fold_parity(
        lambda: rx.box(PlainComp.create()),
        {PlainComp.create: {"outline": "1px solid"}},
    )
    assert "1px solid" in js


def test_instance_style_wins_over_app_and_add_style():
    js = _assert_fold_parity(
        lambda: AddStyleComp.create(style={"color": "yellow"}),
        {AddStyleComp: {"color": "orange"}},
    )
    assert "yellow" in js


def test_whole_style_var_kwarg_folds():
    # `style=<Var>` is wrapped by `_post_init` into `{"&": var}`; on a
    # folding node (add_style chain) the fold must carry the var and its
    # VarData through the merge.
    style_var = Var(
        "dynStyles",
        _var_data=VarData(imports={"my-style-lib": [ImportVar(tag="dynStyles")]}),
    ).to(dict)

    js = _assert_fold_parity(lambda: rx.box(AddStyleComp.create(style=style_var)), {})
    assert "dynStyles" in js


def test_breakpoints_and_pseudo_with_app_style():
    js = _assert_fold_parity(
        lambda: rx.box(
            rx.text(
                "responsive",
                style={
                    "color": Breakpoints(initial="red", md="blue"),
                    "_hover": {"color": "green"},
                },
            )
        ),
        {type(rx.text("x")): {"font_size": ["1em", "2em"]}},
    )
    assert "@media" in js


def test_foreach_body_with_add_style_class():
    _assert_fold_parity(
        lambda: rx.box(rx.foreach(Var.create(["a", "b"]), lambda item: rx.text(item))),
        {type(rx.text("x")): {"letter_spacing": "1px"}},
    )


def test_match_bodies_fold():
    from reflex_components_core.core.match import Match

    js = _assert_fold_parity(
        lambda: rx.box(
            Match.create(
                Var("matchVal", _var_data=VarData()).to(str),
                ("a", AddStyleComp.create()),
                ("b", rx.text("b-case")),
                rx.text("default-case"),
            )
        ),
        {type(rx.text("x")): {"text_transform": "uppercase"}},
    )
    assert "uppercase" in js
    assert "red" in js


def test_cond_branches_fold():
    js = _assert_fold_parity(
        lambda: rx.box(
            rx.cond(
                Var("condVal", _var_data=VarData()).to(bool),
                AddStyleComp.create(),
                rx.text("else-side"),
            )
        ),
        {type(rx.text("x")): {"font_style": "italic"}},
    )
    assert "italic" in js
    assert "red" in js


def test_app_style_scope_excludes_wrapper_and_meta_nodes():
    from reflex_components_core.el.elements.metadata import Title

    # `add_meta` appends a Title node AFTER the legacy fold ran, so an
    # App.style entry for Title styles only the user's in-tree Title —
    # never the page-meta one. Byte parity pins the deferred fold to the
    # same scope (a whole-tree fold would style both).
    js = _assert_fold_parity(
        lambda: rx.box(Title.create("in-tree title")),
        {Title: {"color": "tomato"}},
    )
    assert js.count("tomato") == 1


def test_style_var_data_imports_survive_fold():
    themed = Var(
        "themedColor",
        _var_data=VarData(imports={"theme-lib": [ImportVar(tag="themedColor")]}),
    ).to(str)
    _, _, imports = _compile(
        lambda: rx.box(PlainComp.create(style={"color": themed})),
        {PlainComp: {"border_color": themed}},
        deferred=True,
    )
    assert "theme-lib" in imports
    _assert_fold_parity(
        lambda: rx.box(PlainComp.create(style={"color": themed})),
        {PlainComp: {"border_color": themed}},
    )


def test_overriding_add_style_underscore_raises_on_both_paths():
    class BadComp(Component):
        tag = "BadComp"
        library = "style-fold-lib"

        def _add_style(self):
            return {}

    with pytest.raises(UserWarning):
        _compile(lambda: rx.box(BadComp.create()), {}, deferred=False)
    with pytest.raises(Exception, match="add_style"):
        _compile(lambda: rx.box(BadComp.create()), {}, deferred=True)


def test_apply_style_flag_marks_fold_root_instead_of_folding():
    unev = UnevaluatedPage(component=lambda: rx.box(rx.text("m")), route="/m")
    folded = compile_unevaluated_page("/m", unev, {}, None, apply_style=True)
    assert "_style_fold_root" not in folded.children[0].__dict__
    deferred = compile_unevaluated_page("/m", unev, {}, None, apply_style=False)
    assert deferred.children[0].__dict__.get("_style_fold_root") is True
    # The wrapper Fragment and the meta siblings never carry the mark.
    assert "_style_fold_root" not in deferred.__dict__
    for sibling in deferred.children[1:]:
        assert "_style_fold_root" not in sibling.__dict__


def _compile_pages_output(
    tmp_path, monkeypatch, app_style: dict, env_value: str | None
) -> dict[str, str]:
    from reflex.compiler import rust_pipeline
    from reflex.utils import prerequisites

    web = tmp_path / ".web"
    web.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(prerequisites, "get_web_dir", lambda: web)
    if env_value is None:
        monkeypatch.delenv("REFLEX_STYLE_FOLD", raising=False)
    else:
        monkeypatch.setenv("REFLEX_STYLE_FOLD", env_value)
    monkeypatch.setenv("REFLEX_COMPILE_CACHE", "0")

    app = rx.App(style={AddStyleComp: {"color": "teal"}})
    app.add_page(lambda: rx.box(AddStyleComp.create(), rx.text("kill")), route="/")
    written, _ = rust_pipeline.compile_pages(app, session=CompilerSession())
    return {route: path.read_text() for route, path in written.items()}


def test_kill_switch_restores_python_fold(tmp_path, monkeypatch):
    # End-to-end through compile_pages: fold-on (default) and fold-off
    # (REFLEX_STYLE_FOLD=0, the legacy Python walk) must emit identical
    # bytes — and the app style must actually land in them.
    fold_on = _compile_pages_output(tmp_path / "on", monkeypatch, {}, None)
    fold_off = _compile_pages_output(tmp_path / "off", monkeypatch, {}, "0")
    assert fold_on == fold_off
    assert "teal" in fold_on["index"]
