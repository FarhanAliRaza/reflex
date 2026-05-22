"""Local-first deploy and launch helpers for Reflex Notebooks.

``deploy(name)`` writes the generated Reflex app to disk and stops there — useful when
the user wants to inspect or edit the source before running anything. ``launch(name)``
goes a step further: it writes the app, spawns ``reflex run`` as a child process, and
returns a clickable URL the user can open straight from the notebook.

A single child process is tracked module-wide; calling ``launch()`` again terminates the
previous server before starting a new one, and the same handler runs at interpreter exit.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from reflex.notebook.codegen import generate_app_source
from reflex.notebook.runtime import NotebookRuntime, get_runtime

_running: dict[str, Any] = {"proc": None, "url": None, "base": None}
_atexit_registered = False


def deploy(
    app_name: str = "notebook_app",
    target_dir: str | Path | None = None,
    runtime: NotebookRuntime | None = None,
) -> str:
    """Materialize the runtime as a Reflex app on disk without starting a server.

    Args:
        app_name: A slug used for the generated module and rxconfig.
        target_dir: Where to write the app. Defaults to ``./<app_name>/``.
        runtime: Optional runtime override; defaults to the process-wide runtime.

    Returns:
        The default local URL the app would be served on once launched.
    """
    base = _materialize(app_name=app_name, target_dir=target_dir, runtime=runtime)
    sys.stdout.write(
        f"Wrote Reflex app to {base}.\n"
        f"  cd {base} && uv run reflex run"
        f"    # or call rx.notebook.launch({app_name!r}) to start it now\n"
    )
    return "http://localhost:3000"


def launch(
    app_name: str = "notebook_app",
    target_dir: str | Path | None = None,
    runtime: NotebookRuntime | None = None,
    frontend_port: int = 3000,
    backend_port: int = 8000,
    env: str = "dev",
    open_browser: bool = False,
) -> str:
    """Materialize the runtime as a Reflex app and start it locally.

    Spawns ``reflex run`` as a subprocess in the generated directory and streams its
    output to stdout so the user can see compile/startup progress. A previously
    launched server is terminated before starting a new one.

    Args:
        app_name: A slug used for the generated module and rxconfig.
        target_dir: Where to write the app. Defaults to ``./<app_name>/``.
        runtime: Optional runtime override; defaults to the process-wide runtime.
        frontend_port: TCP port for the compiled frontend (default 3000).
        backend_port: TCP port for the FastAPI backend (default 8000).
        env: Reflex environment to pass through (``dev`` or ``prod``).
        open_browser: When True, open the URL in the user's default browser.

    Returns:
        The local URL the app is being served on.
    """
    stop()
    base = _materialize(app_name=app_name, target_dir=target_dir, runtime=runtime)
    reflex_cli = _find_reflex_cli()
    cmd = [
        reflex_cli,
        "run",
        "--env",
        env,
        "--frontend-port",
        str(frontend_port),
        "--backend-port",
        str(backend_port),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(base),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    url = f"http://localhost:{frontend_port}"
    _running["proc"] = proc
    _running["url"] = url
    _running["base"] = base
    threading.Thread(target=_drain_logs, args=(proc,), daemon=True).start()
    _register_atexit()
    _render_launch_banner(url=url, base=base)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    return url


def stop() -> None:
    """Terminate the most recently launched dev server, if any."""
    proc = _running.get("proc")
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    _running["proc"] = None
    _running["url"] = None


def _materialize(
    app_name: str,
    target_dir: str | Path | None,
    runtime: NotebookRuntime | None,
) -> Path:
    """Write the generated Reflex app to disk and return the base directory.

    Args:
        app_name: A slug used for the generated module and rxconfig.
        target_dir: Optional override for the target directory.
        runtime: Optional runtime override.

    Returns:
        The base directory the app was written to.
    """
    rt = runtime or get_runtime()
    base = Path(target_dir) if target_dir is not None else Path.cwd() / app_name
    package_dir = base / app_name
    package_dir.mkdir(parents=True, exist_ok=True)
    source = generate_app_source(rt, app_name=app_name)
    (package_dir / f"{app_name}.py").write_text(source)
    (package_dir / "__init__.py").write_text("")
    (base / "rxconfig.py").write_text(
        f"import reflex as rx\n\nconfig = rx.Config(app_name={app_name!r})\n"
    )
    (base / "requirements.txt").write_text("reflex\n")
    return base


def _find_reflex_cli() -> str:
    """Return the path to the ``reflex`` executable to invoke.

    Prefers the ``reflex`` binary that ships in the active interpreter's environment
    so a subprocess won't pick up a stale system install.

    Returns:
        An absolute path or bare command name suitable for ``subprocess``.
    """
    candidate = Path(sys.executable).with_name("reflex")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("reflex")
    return found or "reflex"


def _drain_logs(proc: subprocess.Popen[str]) -> None:
    """Stream a subprocess's combined stdout/stderr to the current stdout.

    Args:
        proc: The subprocess whose output should be forwarded.
    """
    stream = proc.stdout
    if stream is None:
        return
    for line in stream:
        sys.stdout.write(line)
        sys.stdout.flush()


def _register_atexit() -> None:
    """Register ``stop`` to run at interpreter exit (once per process)."""
    global _atexit_registered
    if _atexit_registered:
        return
    atexit.register(stop)
    _atexit_registered = True


def _render_launch_banner(url: str, base: Path) -> None:
    """Render a clickable launch banner inside IPython, or plain text elsewhere.

    Args:
        url: The local URL the app is being served on.
        base: The generated app's base directory.
    """
    try:
        from IPython.display import (  # pyright: ignore[reportMissingImports]
            HTML,
            display,
        )
    except ImportError:
        sys.stdout.write(
            f"Reflex app from {base} starting at {url}.\n"
            f"First build downloads bun/Node and compiles the frontend — give it a minute.\n"
            f"Call rx.notebook.stop() to shut the server down.\n"
        )
        return
    html = (
        '<div style="padding:12px 14px;border:1px solid #5B7CFA;border-radius:8px;'
        'background:#F4F6FF;font-family:system-ui,sans-serif;line-height:1.5;">'
        f"<strong>Reflex app starting</strong> &middot; "
        f'<a href="{url}" target="_blank" style="color:#3252D2;font-weight:600;">{url}</a><br>'
        f'<span style="color:#444;font-size:0.9em;">First build downloads bun/Node and '
        f"compiles the frontend — give it a minute. Call "
        f"<code>rx.notebook.stop()</code> to shut it down. "
        f"Source: <code>{_pretty_path(base)}</code></span>"
        "</div>"
    )
    display(HTML(html))


def _pretty_path(base: Path) -> str:
    """Return a path relative to CWD when possible, otherwise the absolute path.

    Args:
        base: The path to format.

    Returns:
        A short, human-readable representation of ``base``.
    """
    try:
        return str(base.relative_to(Path.cwd()))
    except ValueError:
        return str(base)


def current_launch() -> dict[str, Any]:
    """Return a snapshot of the running launch, if any.

    Returns:
        A dict with keys ``proc``, ``url``, and ``base``; values are ``None`` when no
        server is currently running.
    """
    return {
        "proc": _running.get("proc"),
        "url": _running.get("url"),
        "base": _running.get("base"),
    }
