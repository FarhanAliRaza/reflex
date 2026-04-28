# Reflex Notebooks (MVP)

> Turn any Jupyter notebook into a deployed Reflex app in three lines of Python.

```python
import reflex as rx

rx.notebook()  # one-time init
# ... your existing notebook cells ...
rx.notebook.deploy("my_app")  # generate a runnable Reflex app
```

## What's in the MVP

This is the Phase 1 cut from the project plan: a minimum viable demo.

- **`rx.notebook()`** — register IPython hooks so subsequent cells are tracked.
- **Seven input primitives** at `rx.notebook.*`: `select`, `slider`, `text_input`,
  `checkbox`, `date_picker`, `file_upload`, `button`.
- **Output dispatch** for the five common kinds: pandas DataFrame, matplotlib
  figure, plotly figure, primitives (str/int/float/bool/None), and any object
  with `_repr_html_` (HTML / Markdown).
- **`rx.notebook.row(...)`** for horizontal layout. Default is vertical stacking.
- **Re-execution model**: when an input changes, all cells that ran *after* the
  cell which created the widget are re-executed. Streamlit-style; wasteful but
  correct.
- **`rx.notebook.view_source()`** — print the Reflex source the notebook would
  compile to. This is the on-ramp into the full framework.
- **`rx.notebook.deploy("my_app")`** — write the generated `app.py`,
  `rxconfig.py`, and `requirements.txt` into a directory and print the
  `reflex run` command.

## What's intentionally out of scope (yet)

- Reflex Cloud upload — `deploy()` writes locally and prints the run command;
  cloud wiring is Phase 3.
- JupyterLab / VS Code extensions — Phase 2.
- Dependency-graph re-execution (Marimo-style) — explicitly skipped per plan.
- Auth / custom subdomains — Phase 3.
- Codegen for arbitrary cell bodies — the generated app preserves widget
  structure and output kind, but cell bodies are not transpiled. The output is
  a starting point you customize.

## Try it

```bash
jupyter lab reflex/notebook/quickstart.ipynb
```

## Architecture

```
reflex/notebook/
    __init__.py    # public API; module is callable for shorthand init
    runtime.py     # cell tracking, widget registry, IPython hooks, re-execution
    widgets.py     # the seven input primitives
    outputs.py     # output classification + IPython display dispatch
    layout.py      # row()
    codegen.py     # Reflex source generator
    deploy.py      # local app materializer
```

The runtime is the only stateful piece. Everything else is a thin wrapper that
records on the runtime so `view_source()` and `deploy()` can reproduce the
notebook structure.

## Testing

```bash
uv run pytest tests/units/notebook --no-cov
```

60 unit tests cover the runtime, widgets, outputs, layout, codegen, and the
public namespace.
