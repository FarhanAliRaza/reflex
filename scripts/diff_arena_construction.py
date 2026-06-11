"""Per-page byte diff of rich vs arena construction, via fork pairs.

For each route of the app in the current directory, fork twice from the
same parent state: child A evaluates and compiles the page with the arena
construction scope OFF (full ``_post_init``), child B with it ON (the
mirror fast path). Both children inherit identical interpreter state —
random seeds, unique-name counters, the Rust intern table — so their
outputs are exactly byte-comparable: the only possible difference is the
construction path itself. This sidesteps every class of evaluation
nondeterminism (upload/data-editor random identifiers, state-name
counters, memo symbol churn) that defeats run-to-run or cross-process
comparison of full compiles.

Run from an app directory: ``uv run python <repo>/scripts/diff_arena_construction.py``.
Exits non-zero on any byte mismatch or per-page error.
"""

import hashlib
import inspect as _inspect
import os
import pickle
import sys
import tempfile
import time
import typing as _typing

# Python 3.14 / pydantic 2.13 compat shim (see tests/units/conftest.py).
_orig_eval_type = _typing._eval_type
_params = _inspect.signature(_orig_eval_type).parameters
if "prefer_fwd_module" not in _params:

    def _eval_type_compat(*args, **kwargs):
        return _orig_eval_type(
            *args, **{k: v for k, v in kwargs.items() if k in _params}
        )

    _typing._eval_type = _eval_type_compat

sys.path.insert(0, str(__import__("pathlib").Path.cwd()))

import pathlib

from reflex_base.components.component import arena_construction

from reflex.compiler.compiler import compile_unevaluated_page
from reflex.compiler.rust_pipeline import _route_to_ident
from reflex.utils import prerequisites


def _compile_in_child(
    app: object, route: str, unev: object, arena: bool, out_path: str
) -> int:
    """Fork; in the child, compile one page and pickle its digest.

    Args:
        app: The loaded app.
        route: The route to compile.
        unev: The route's UnevaluatedPage.
        arena: Whether to evaluate under the arena construction scope.
        out_path: Where the child pickles its result digest.

    Returns:
        The child pid (parent side).
    """
    pid = os.fork()
    if pid:
        return pid
    try:
        from reflex.compiler.session import CompilerSession

        with arena_construction(arena):
            component = compile_unevaluated_page(
                route, unev, app.style, app.theme, apply_style=False
            )
        sess = CompilerSession()
        page_js, bodies, *_ = sess.compile_page_from_component_arena(
            component, _route_to_ident(route), route, app_style=app.style or {}
        )
        digest = {
            "page": hashlib.sha256(page_js.encode()).hexdigest(),
            "bodies": sorted(
                (n, hashlib.sha256(j.encode()).hexdigest()) for n, j in bodies
            ),
        }
        with pathlib.Path(out_path).open("wb") as f:
            pickle.dump(digest, f)
        os._exit(0)
    except BaseException as e:
        with pathlib.Path(out_path).open("wb") as f:
            pickle.dump({"error": f"{type(e).__name__}: {e}"}, f)
        os._exit(1)


def main() -> int:
    """Compare every page rich-vs-arena; print a summary.

    Returns:
        Process exit code (0 = all pages byte-identical).
    """
    app = prerequisites.get_and_validate_app().app
    app._apply_decorated_pages()

    t0 = time.monotonic()
    mismatched: list[str] = []
    errors: list[tuple[str, str | None, str | None]] = []
    with tempfile.TemporaryDirectory() as td:
        for i, (route, unev) in enumerate(app._unevaluated_pages.items()):
            path_a, path_b = f"{td}/a_{i}", f"{td}/b_{i}"
            os.waitpid(_compile_in_child(app, route, unev, False, path_a), 0)
            os.waitpid(_compile_in_child(app, route, unev, True, path_b), 0)
            with pathlib.Path(path_a).open("rb") as f:
                digest_a = pickle.load(f)
            with pathlib.Path(path_b).open("rb") as f:
                digest_b = pickle.load(f)
            if "error" in digest_a or "error" in digest_b:
                errors.append((route, digest_a.get("error"), digest_b.get("error")))
            elif digest_a != digest_b:
                mismatched.append(route)

    total = len(app._unevaluated_pages)
    print(f"compared {total} pages in {time.monotonic() - t0:.1f}s")
    print(f"mismatched: {len(mismatched)} {mismatched[:20]}")
    print(f"errors: {len(errors)} {errors[:5]}")
    return 1 if (mismatched or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
