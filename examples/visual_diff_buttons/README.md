# Button visual diff harness

Side-by-side comparison page that renders the current
``rx.button`` (Radix Themes, ``@radix-ui/themes`` precompiled CSS) next to
the new ``shadcn_button`` (Tailwind utilities + Radix Primitives) for
every variant/size pair. Lets you visually verify pixel parity before
swapping the implementation in ``reflex-components-radix``.

## Run

```
cd examples/visual_diff_buttons
uv sync
uv run reflex run
```

Then open http://localhost:3000.

## Capture screenshots

In a second terminal while ``reflex run`` is up:

```
uv run playwright install chromium
uv run python capture.py
```

Screenshots land in ``screenshots/``:

- ``buttons.png`` — full page
- ``buttons-size-1.png`` … ``buttons-size-4.png`` — one row per size

Each row pairs every Radix variant with its closest shadcn equivalent.
The mapping is documented in ``visual_diff_buttons.py``.
