"""Tests for the dependency-keyed page compile cache (reflex/compiler/cache.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("reflex_base")
pytest.importorskip("reflex_components_core")
pytest.importorskip("reflex_compiler_rust._native")

import reflex as rx
from reflex.app import UnevaluatedPage
from reflex.compiler import rust_pipeline
from reflex.compiler.cache import CompileCache, _stable_token
from reflex.compiler.session import CompilerSession


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal on-disk project, importable from the project root.

    Args:
        tmp_path: pytest tmp dir to build the project in.
        monkeypatch: used to prepend the project root to sys.path.

    Returns:
        The project root containing a page module, its helper, and an
        unrelated module.
    """
    (tmp_path / "helpers.py").write_text('GREETING = "hello cache"\n')
    (tmp_path / "unrelated.py").write_text("OTHER = 1\n")
    (tmp_path / "pages.py").write_text(
        "import reflex as rx\n"
        "from helpers import GREETING\n"
        "\n"
        "def index():\n"
        "    return rx.text(GREETING)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


@pytest.fixture
def cache(project: Path) -> CompileCache:
    return CompileCache(project, project / ".web" / ".rxcache", [])


def _import_pages(project: Path):
    """(Re)import the project's page module fresh from disk.

    Args:
        project: The project root (already on sys.path).

    Returns:
        The freshly imported ``pages`` module.
    """
    sys.modules.pop("pages", None)
    sys.modules.pop("helpers", None)
    import importlib

    return importlib.import_module("pages")


def _unev(page_fn, route: str = "index", **kwargs) -> UnevaluatedPage:
    return UnevaluatedPage(component=page_fn, route=route, **kwargs)


def test_stable_token_basic_values():
    assert _stable_token(None) == "None"
    assert _stable_token("title") == "'title'"
    assert _stable_token((1, "a", None)) == "[1,'a',None]"
    assert _stable_token({"b": 2, "a": 1}) == "{'a':1,'b':2}"


def test_stable_token_var_uses_js_expr():
    var = rx.Var.create("xyz")
    token = _stable_token(var)
    assert token is not None
    assert token.startswith("var:")
    assert _stable_token(var) == token


def test_stable_token_unstable_objects_return_none():
    assert _stable_token(object()) is None
    assert _stable_token(rx.text("inline component")) is None
    assert _stable_token([1, object()]) is None


def test_stable_token_callable_uses_qualname():
    def handler():
        pass

    token = _stable_token(handler)
    assert token is not None
    assert "handler" in token


def test_key_for_uncacheable_pages(project: Path, cache: CompileCache):
    # Prebuilt component instances have no source module.
    assert cache.key_for("index", _unev(rx.text("static"))) is None
    # Callables defined outside the project root (this test file).
    assert cache.key_for("index", _unev(lambda: rx.text("x"))) is None
    # Unstable metadata.
    pages = _import_pages(project)
    unev = _unev(pages.index, meta=[rx.text("component meta")])
    assert cache.key_for("index", unev) is None


def test_key_is_deterministic_and_route_scoped(project: Path, cache: CompileCache):
    pages = _import_pages(project)
    unev = _unev(pages.index)
    key = cache.key_for("index", unev)
    assert key is not None
    assert cache.key_for("index", unev) == key
    assert cache.key_for("other", unev) != key


def test_key_changes_with_page_module(project: Path, cache: CompileCache):
    pages = _import_pages(project)
    unev = _unev(pages.index)
    key_before = cache.key_for("index", unev)
    page_src = (project / "pages.py").read_text()
    (project / "pages.py").write_text(page_src + "\nEXTRA = 1\n")
    assert cache.key_for("index", unev) != key_before


def test_key_changes_with_transitive_dep(project: Path, cache: CompileCache):
    pages = _import_pages(project)
    unev = _unev(pages.index)
    key_before = cache.key_for("index", unev)
    (project / "helpers.py").write_text('GREETING = "changed"\n')
    assert cache.key_for("index", unev) != key_before


def test_key_ignores_unrelated_file(project: Path, cache: CompileCache):
    pages = _import_pages(project)
    unev = _unev(pages.index)
    key_before = cache.key_for("index", unev)
    (project / "unrelated.py").write_text("OTHER = 2\n")
    assert cache.key_for("index", unev) == key_before


def test_key_changes_with_metadata(project: Path, cache: CompileCache):
    pages = _import_pages(project)
    key_a = cache.key_for("index", _unev(pages.index, title="A"))
    key_b = cache.key_for("index", _unev(pages.index, title="B"))
    assert key_a is not None
    assert key_a != key_b


def test_key_changes_with_base_dep_file(project: Path):
    main = project / "main_app.py"
    main.write_text("THEME = 1\n")
    cache = CompileCache(project, project / ".web" / ".rxcache", [main])
    pages = _import_pages(project)
    unev = _unev(pages.index)
    key_before = cache.key_for("index", unev)
    main.write_text("THEME = 2\n")
    assert cache.key_for("index", unev) != key_before


def test_relative_import_resolution(project: Path, cache: CompileCache):
    pkg = project / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "sibling.py").write_text("VALUE = 1\n")
    (pkg / "page.py").write_text(
        "import reflex as rx\n"
        "from .sibling import VALUE\n"
        "\n"
        "def page():\n"
        "    return rx.text(str(VALUE))\n"
    )
    import importlib

    sys.modules.pop("mypkg", None)
    sys.modules.pop("mypkg.page", None)
    mod = importlib.import_module("mypkg.page")
    unev = _unev(mod.page)
    key_before = cache.key_for("index", unev)
    assert key_before is not None
    (pkg / "sibling.py").write_text("VALUE = 2\n")
    assert cache.key_for("index", unev) != key_before


def test_put_lookup_roundtrip_and_persistence(project: Path, cache: CompileCache):
    entry = {
        "page_js": "export default function Component() {}",
        "memo_bodies": [("Memo_abc", "jsx body")],
        "imports": {"react": []},
        "app_wraps": {},
        "stateful": False,
    }
    cache.put("index", "k" * 64, entry)
    assert cache.lookup("index", "k" * 64) == entry
    assert cache.lookup("index", "x" * 64) is None
    assert cache.lookup("missing", "k" * 64) is None
    cache.save()

    reloaded = CompileCache(project, project / ".web" / ".rxcache", [])
    assert reloaded.lookup("index", "k" * 64) == entry


def test_pin_uncacheable_is_sticky(project: Path, cache: CompileCache):
    cache.pin_uncacheable("index")
    cache.put("index", "k" * 64, {"page_js": "x"})
    assert cache.lookup("index", "k" * 64) is None
    cache.save()
    reloaded = CompileCache(project, project / ".web" / ".rxcache", [])
    reloaded.put("index", "k" * 64, {"page_js": "x"})
    assert reloaded.lookup("index", "k" * 64) is None


def test_put_unpicklable_entry_pins_uncacheable(project: Path, cache: CompileCache):
    """An entry that can't pickle pins the route instead of raising.

    Regression: DataEditor's app-wrap Portal is a class defined inside a
    method, which pickle rejects — that crashed the whole build at put().
    """

    class _Local:
        pass

    cache.put("index", "k" * 64, {"page_js": "x", "app_wraps": {(-1, "P"): _Local}})
    assert cache.lookup("index", "k" * 64) is None
    # The pin is sticky: a later picklable entry is not stored either.
    cache.put("index", "k" * 64, {"page_js": "x"})
    assert cache.lookup("index", "k" * 64) is None


def test_compiler_rebuild_invalidates_manifest(
    project: Path, cache: CompileCache, monkeypatch: pytest.MonkeyPatch
):
    """A rebuilt native compiler invalidates every cached page.

    Regression: the manifest was keyed on the Reflex version only, so after
    ``maturin develop`` changed the emitter, cache hits replayed stale page
    artifacts (e.g. pages missing the memo-wrapper import fix).
    """
    from reflex.compiler import cache as cache_mod

    entry = {"page_js": "old output"}
    cache.put("index", "k" * 64, entry)
    cache.save()

    same = CompileCache(project, project / ".web" / ".rxcache", [])
    assert same.lookup("index", "k" * 64) == entry

    monkeypatch.setattr(cache_mod, "_compiler_fingerprint", lambda: "rebuilt:123")
    rebuilt = CompileCache(project, project / ".web" / ".rxcache", [])
    assert rebuilt.lookup("index", "k" * 64) is None


def test_save_prunes_orphaned_blobs(project: Path, cache: CompileCache):
    cache.put("index", "a" * 64, {"page_js": "old"})
    cache.put("index", "b" * 64, {"page_js": "new"})
    cache.save()
    blobs = list((project / ".web" / ".rxcache" / "blobs").glob("*.pkl"))
    assert [b.stem for b in blobs] == ["b" * 64]


def test_default_disabled_by_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFLEX_COMPILE_CACHE", "0")
    assert CompileCache.default("dev") is None


@pytest.fixture
def web_dir(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from reflex.utils import prerequisites

    web = project / ".web"
    web.mkdir(exist_ok=True)
    monkeypatch.setattr(prerequisites, "get_web_dir", lambda: web)
    return web


@pytest.fixture
def eval_counter(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count compile_unevaluated_page calls per route inside compile_pages.

    Args:
        monkeypatch: used to wrap the real compile_unevaluated_page.

    Returns:
        A live mapping of route -> evaluation count.
    """
    from reflex.compiler import compiler as compiler_mod

    counts: dict[str, int] = {}
    real = compiler_mod.compile_unevaluated_page

    def counting(route, *args, **kwargs):
        counts[route] = counts.get(route, 0) + 1
        return real(route, *args, **kwargs)

    monkeypatch.setattr(compiler_mod, "compile_unevaluated_page", counting)
    return counts


def test_compile_pages_cache_hit_skips_evaluation(
    project: Path, web_dir: Path, eval_counter: dict[str, int]
):
    pages = _import_pages(project)
    app = rx.App()
    app.add_page(pages.index, route="/")
    session = CompilerSession()

    cache_dir = web_dir / ".rxcache"
    written_cold, _ = rust_pipeline.compile_pages(
        app, session=session, cache=CompileCache(project, cache_dir, [])
    )
    assert eval_counter["index"] == 1
    cold_jsx = written_cold["index"].read_text()
    assert "hello cache" in cold_jsx

    # Fresh cache instance = new process; the page must restore without
    # evaluating and produce identical output.
    written_warm, _ = rust_pipeline.compile_pages(
        app, session=session, cache=CompileCache(project, cache_dir, [])
    )
    assert eval_counter["index"] == 1
    assert written_warm["index"].read_text() == cold_jsx


def test_compile_pages_recompiles_on_dep_change(
    project: Path, web_dir: Path, eval_counter: dict[str, int]
):
    pages = _import_pages(project)
    app = rx.App()
    app.add_page(pages.index, route="/")
    session = CompilerSession()
    cache_dir = web_dir / ".rxcache"

    rust_pipeline.compile_pages(
        app, session=session, cache=CompileCache(project, cache_dir, [])
    )
    (project / "helpers.py").write_text('GREETING = "edited"\n')
    pages = _import_pages(project)
    app = rx.App()
    app.add_page(pages.index, route="/")
    written, _ = rust_pipeline.compile_pages(
        app, session=session, cache=CompileCache(project, cache_dir, [])
    )
    assert eval_counter["index"] == 2
    assert "edited" in written["index"].read_text()


@pytest.fixture
def clean_fake_states():
    """Remove the fake state-registry entries the sneaky page adds."""
    from reflex.state import all_base_state_classes

    yield
    for name in [k for k in all_base_state_classes if k.startswith("Fake")]:
        del all_base_state_classes[name]


def test_compile_pages_pins_state_registering_page(
    project: Path,
    web_dir: Path,
    eval_counter: dict[str, int],
    clean_fake_states: None,
):
    (project / "stateful_pages.py").write_text(
        "import reflex as rx\n"
        "from reflex.state import all_base_state_classes\n"
        "\n"
        "def sneaky():\n"
        "    all_base_state_classes[f'Fake{len(all_base_state_classes)}'] = None\n"
        "    return rx.text('side effect')\n"
    )
    import importlib

    sys.modules.pop("stateful_pages", None)
    mod = importlib.import_module("stateful_pages")
    app = rx.App()
    app.add_page(mod.sneaky, route="/")
    session = CompilerSession()
    cache_dir = web_dir / ".rxcache"

    rust_pipeline.compile_pages(
        app, session=session, cache=CompileCache(project, cache_dir, [])
    )
    rust_pipeline.compile_pages(
        app, session=session, cache=CompileCache(project, cache_dir, [])
    )
    # Both runs evaluated: the route is pinned uncacheable.
    assert eval_counter["index"] == 2
