import pytest
from reflex_base.config import get_config
from reflex_base.utils.exceptions import CompileError

from reflex import text
from reflex.page import DECORATED_PAGES, page


def test_page_decorator():
    def foo_():
        return text("foo")

    DECORATED_PAGES.clear()
    assert len(DECORATED_PAGES) == 0
    decorated_foo_ = page()(foo_)
    assert decorated_foo_ == foo_
    assert len(DECORATED_PAGES) == 1
    page_data = DECORATED_PAGES.get(get_config().app_name, [])[0][1]
    assert page_data == {}
    DECORATED_PAGES.clear()


def test_page_decorator_with_kwargs():
    def foo_():
        return text("foo")

    def load_foo():
        return []

    DECORATED_PAGES.clear()
    assert len(DECORATED_PAGES) == 0
    decorated_foo_ = page(
        route="foo",
        title="Foo",
        image="foo.png",
        description="Foo description",
        meta=[{"name": "keywords", "content": "foo, test"}],
        script_tags=["foo-script"],
        on_load=load_foo,
    )(foo_)
    assert decorated_foo_ == foo_
    assert len(DECORATED_PAGES) == 1
    page_data = DECORATED_PAGES.get(get_config().app_name, [])[0][1]
    assert page_data == {
        "description": "Foo description",
        "image": "foo.png",
        "meta": [{"name": "keywords", "content": "foo, test"}],
        "on_load": load_foo,
        "route": "foo",
        "script_tags": ["foo-script"],
        "title": "Foo",
    }

    DECORATED_PAGES.clear()


@pytest.mark.parametrize("mode", ["static", "app", "islands"])
def test_page_decorator_render_mode_round_trip(mode: str):
    """Each valid render_mode is stored on the decorated page record."""

    def foo_():
        return text("foo")

    DECORATED_PAGES.clear()
    page(route=f"/r-{mode}", render_mode=mode)(foo_)  # pyright: ignore[reportArgumentType]
    page_data = DECORATED_PAGES.get(get_config().app_name, [])[-1][1]
    assert page_data["render_mode"] == mode
    DECORATED_PAGES.clear()


def test_page_decorator_render_mode_default_unset():
    """When render_mode is not passed, it must not appear in page kwargs."""

    def foo_():
        return text("foo")

    DECORATED_PAGES.clear()
    page(route="/no-mode")(foo_)
    page_data = DECORATED_PAGES.get(get_config().app_name, [])[-1][1]
    assert "render_mode" not in page_data
    DECORATED_PAGES.clear()


def test_page_decorator_invalid_render_mode():
    """Invalid render_mode raises CompileError before DECORATED_PAGES is touched."""

    def foo_():
        return text("foo")

    DECORATED_PAGES.clear()
    with pytest.raises(CompileError, match="Invalid render_mode"):
        page(route="/bad", render_mode="ssr")(foo_)  # pyright: ignore[reportArgumentType]
    assert len(DECORATED_PAGES) == 0


@pytest.mark.parametrize("mode", ["static", "islands"])
def test_page_decorator_on_load_only_with_app_mode(mode: str):
    """on_load combined with non-app render_mode is a CompileError."""

    def foo_():
        return text("foo")

    def load_foo():
        return []

    DECORATED_PAGES.clear()
    with pytest.raises(CompileError, match="on_load is only supported"):
        page(route="/x", render_mode=mode, on_load=load_foo)(foo_)  # pyright: ignore[reportArgumentType]
    assert len(DECORATED_PAGES) == 0


def test_page_decorator_on_load_with_app_mode_ok():
    """on_load + render_mode='app' is allowed."""

    def foo_():
        return text("foo")

    def load_foo():
        return []

    DECORATED_PAGES.clear()
    page(route="/y", render_mode="app", on_load=load_foo)(foo_)
    page_data = DECORATED_PAGES.get(get_config().app_name, [])[-1][1]
    assert page_data["render_mode"] == "app"
    assert page_data["on_load"] is load_foo
    DECORATED_PAGES.clear()
