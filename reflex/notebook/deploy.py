"""Local-first deploy helper for Reflex Notebooks.

Phase 1 writes the generated app and a minimal ``rxconfig.py`` to a target directory and
returns the local URL the user should visit. Wiring this into Reflex Cloud is intentionally
out of scope for the MVP; the function instead prints the exact ``reflex run`` invocation
that turns the generated directory into a live app.
"""

from __future__ import annotations

from pathlib import Path

from reflex.notebook.codegen import generate_app_source
from reflex.notebook.runtime import NotebookRuntime, get_runtime


def deploy(
    app_name: str = "notebook_app",
    target_dir: str | Path | None = None,
    runtime: NotebookRuntime | None = None,
) -> str:
    """Materialize the runtime as a Reflex app on disk.

    Args:
        app_name: A slug used for the generated module and rxconfig.
        target_dir: Where to write the app. Defaults to ``./<app_name>/``.
        runtime: Optional runtime override; defaults to the process-wide runtime.

    Returns:
        A local URL the user can visit once they run ``reflex run`` in ``target_dir``.
    """
    rt = runtime or get_runtime()
    base = Path(target_dir) if target_dir is not None else Path.cwd() / app_name
    base.mkdir(parents=True, exist_ok=True)
    package_dir = base / app_name
    package_dir.mkdir(parents=True, exist_ok=True)

    source = generate_app_source(rt, app_name=app_name)
    (package_dir / f"{app_name}.py").write_text(source)
    (package_dir / "__init__.py").write_text("")

    (base / "rxconfig.py").write_text(
        f"import reflex as rx\n\nconfig = rx.Config(app_name={app_name!r})\n"
    )
    (base / "requirements.txt").write_text("reflex\n")

    print(  # noqa: T201
        f"Wrote Reflex app to {base}.\n"
        f"  cd {base} && uv run reflex run\n"
        f"Reflex Cloud upload is not wired into the MVP yet — see view_source() to inspect the generated app."
    )
    return "http://localhost:3000"
