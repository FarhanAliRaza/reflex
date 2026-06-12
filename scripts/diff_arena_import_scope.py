"""Process-level A/B: rich app import vs the staged (default) app import.

Forks once per MODE from a parent that has NOT imported the app, so both
children inherit identical pre-import interpreter state (random seeds,
unique-name counters, an empty intern table). Each child sets the env,
imports the app, compiles every page through the production pipeline, and
hashes the artifacts; the parent compares. This validates import-time
construction staging — which the per-page fork-pair harness cannot, since
its children share the parent's imports.

Mode A is ``REFLEX_ARENA_CONSTRUCT=pages`` (page scope only, the rich
import path); mode B is the default (``get_app`` stages the import).

Run from an app directory:
``uv run python <repo>/scripts/diff_arena_import_scope.py``.
"""

import hashlib
import os
import pathlib
import pickle
import sys
import tempfile
import time


def _compile_all_in_child(mode_env: str, out_path: str) -> int:
    """Fork; the child sets the env, imports the app, compiles, dumps.

    Args:
        mode_env: Value for REFLEX_ARENA_CONSTRUCT in the child.
        out_path: Where the child pickles its digests.

    Returns:
        The child pid (parent side).
    """
    pid = os.fork()
    if pid:
        return pid
    try:
        if mode_env:
            os.environ["REFLEX_ARENA_CONSTRUCT"] = mode_env
        else:
            os.environ.pop("REFLEX_ARENA_CONSTRUCT", None)
        os.environ.setdefault("CI", "1")
        os.environ["REFLEX_COMPILE_CACHE"] = "0"

        import inspect as _inspect
        import typing as _typing

        _orig = _typing._eval_type
        _params = _inspect.signature(_orig).parameters
        if "prefer_fwd_module" not in _params:
            _typing._eval_type = lambda *a, **k: _orig(
                *a, **{x: v for x, v in k.items() if x in _params}
            )
        sys.path.insert(0, str(pathlib.Path.cwd()))

        from reflex.compiler.compiler import compile_unevaluated_page
        from reflex.compiler.rust_pipeline import _route_to_ident
        from reflex.compiler.session import CompilerSession
        from reflex.utils import prerequisites

        app = prerequisites.get_and_validate_app().app
        app._apply_decorated_pages()
        sess = CompilerSession()
        digests = {"mode_default": prerequisites._stage_app_imports(), "pages": {}}
        for route, unev in app._unevaluated_pages.items():
            component = compile_unevaluated_page(
                route, unev, app.style, app.theme, apply_style=False
            )
            page_js, bodies, *_ = sess.compile_page_from_component_arena(
                component, _route_to_ident(route), route, app_style=app.style or {}
            )
            digests["pages"][route] = (
                hashlib.sha256(page_js.encode()).hexdigest(),
                sorted(hashlib.sha256(j.encode()).hexdigest() for _, j in bodies),
            )
        with pathlib.Path(out_path).open("wb") as f:
            pickle.dump(digests, f)
        os._exit(0)
    except BaseException as e:
        with pathlib.Path(out_path).open("wb") as f:
            pickle.dump({"error": f"{type(e).__name__}: {e}"}, f)
        os._exit(1)


def main() -> int:
    """Compare the two modes page-by-page.

    Returns:
        Process exit code (0 = byte-identical).
    """
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as td:
        path_a, path_b = f"{td}/a", f"{td}/b"
        os.waitpid(_compile_all_in_child("pages", path_a), 0)
        os.waitpid(_compile_all_in_child("", path_b), 0)
        with pathlib.Path(path_a).open("rb") as f:
            da = pickle.load(f)
        with pathlib.Path(path_b).open("rb") as f:
            db = pickle.load(f)
    if "error" in da or "error" in db:
        print(f"errors: A={da.get('error')} B={db.get('error')}")
        return 1
    print(
        f"A import staged: {da['mode_default']}  B import staged: {db['mode_default']}"
    )
    mismatched = sorted(r for r in da["pages"] if da["pages"][r] != db["pages"].get(r))
    print(f"compared {len(da['pages'])} pages in {time.monotonic() - t0:.1f}s")
    print(f"mismatched: {len(mismatched)} {mismatched[:20]}")
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
