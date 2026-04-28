```python exec
import reflex as rx
```

# Frontend Inspector

The frontend inspector maps rendered DOM nodes back to the Python source line that created them. Hover an element in the browser, see which `Component.create(...)` call produced it, and click to open that line in your editor.

It is a development-only tool. Enabling it in a production build is a configuration error.

## Enable

Set `frontend_inspector="dev"` in your `rxconfig.py`:

```python
import reflex as rx

config = rx.Config(
    app_name="my_app",
    frontend_inspector="dev",
)
```

Run your app in dev mode (`uv run reflex run`). The inspector loads automatically; the `launch-editor` package is added to `.web/package.json` and installed during the same compile pass.

## Usage

Three modes:

- **Hover with `alt` held** — show the overlay while inspecting. The overlay disappears as soon as you release `alt`.
- **`alt+x`** — toggle persistent mode. The overlay stays on; the small `rx-inspect` button in the bottom-right corner reflects the state.
- **Click** — open the source file at the captured line in your editor.

`Esc` exits persistent mode. Pressing `c` while hovering copies `path:line:column` to the clipboard.

## Configuration

```python
config = rx.Config(
    app_name="my_app",
    frontend_inspector="dev",
    # Custom shortcut. Modifier aliases like cmd / option are accepted.
    frontend_inspector_shortcut="ctrl+shift+i",
    # Optional: override the editor invocation. Empty falls back to
    # $REFLEX_EDITOR / $VISUAL / $EDITOR / launch-editor's auto-detection.
    frontend_inspector_editor="code -g",
)
```

| Field | Default | Notes |
| --- | --- | --- |
| `frontend_inspector` | `"off"` | `"off"` disables it (default), `"dev"` enables it in dev. Prod builds reject `"dev"`. |
| `frontend_inspector_shortcut` | `"alt+x"` | Modifiers: `alt`, `ctrl`, `meta` (`cmd`/`super`/`win`), `shift`. |
| `frontend_inspector_editor` | `""` | Forwarded to [`launch-editor`](https://github.com/yyx990803/launch-editor). |

## Personal preferences via environment variables

The shortcut and editor invocation are personal; you usually do not want to commit them to a shared `rxconfig.py`. Reflex reads the matching env vars at config time:

```bash
REFLEX_FRONTEND_INSPECTOR=dev
REFLEX_FRONTEND_INSPECTOR_SHORTCUT=ctrl+shift+i
REFLEX_FRONTEND_INSPECTOR_EDITOR=cursor
```

Set them in your shell, point Reflex at a dotenv file with `REFLEX_ENV_FILE=.env`, or pass `env_file=".env"` to `rx.Config(...)`. Reflex does not auto-discover a `.env` in the project root.

## Production safety

`frontend_inspector="dev"` raises `ConfigError` whenever `REFLEX_ENV_MODE=prod`, including:

- `uv run reflex run --env prod`
- `uv run reflex export --env prod`
- Any deploy that sets `REFLEX_ENV_MODE=prod`.

The check runs at compile time after the env mode is settled, so the safety net works even when the env is set on the command line.

## What it does and does not do

It does:

- Add a small `data-rx="<id>"` attribute to every component that has a non-Fragment tag.
- Emit `.web/public/__reflex/source-map.json` mapping ids to `(file, line, column, component)`.
- Mount a Vite dev-server middleware at `/__open-in-editor` that calls `launch-editor`.

It does not:

- Inspect React state or props at runtime — it is a source-mapping tool, not a React DevTools replacement.
- Run in production. The plugin is registered with `apply: 'serve'` in Vite, so even if a stray asset slipped through, prod builds would not load it.
- Modify your source code. The inspector stores a private id on each component that gets rendered out as a `data-rx` attribute; your `rxconfig.py` and component files are untouched.

## Programmatic toggle

When the inspector is loaded, `window.__REFLEX_INSPECTOR__` exposes the runtime API for ad-hoc debugging in the browser console:

```js
window.__REFLEX_INSPECTOR__.enable();
window.__REFLEX_INSPECTOR__.toggle();
window.__REFLEX_INSPECTOR__.sourceCount(); // number of mapped ids
```
