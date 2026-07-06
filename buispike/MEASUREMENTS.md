# Spike: Base UI (headless) + atomic theme, end-to-end through Reflex

Goal: validate, with the **real compiler + real Vite build + a real browser**
(not estimates), that a Reflex page built from **headless Base UI** components
styled by an **atomic theme** ships dramatically less CSS than the Radix Themes
runtime stylesheet — and actually renders, themes, and behaves correctly.

The spike contains **two** atomic approaches, both proven end-to-end:

## A. CSS Modules variant (minimal switch)

> **Historical.** This variant's source files (`baseui_switch.py`,
> `switch.module.css`, `_atoms.module.css`) were removed when the spike pivoted
> to the Tailwind approach (variant B, the RFC's recommendation). The numbers
> below are from that earlier build and are not reproducible from this branch.

- `buispike/baseui_switch.py` — Base UI `Switch` wrapped as a
  `CSSModuleComponent`; styling from a co-located atomic module only.
- `buispike/switch.module.css` + `buispike/_atoms.module.css` — the switch's
  rules + shared atoms (`composes`).

Built with `reflex export`; CSS emitted under `.web/build/client`:

| Build | CSS shipped (gz) |
|---|---|
| Base UI + CSS-module (fully migrated, **zero Radix**) | **~2.7 KB** |
| `_baseui_` route chunk alone | **406 B** |
| Radix Themes (implicit, full bundle) | **84 KB** |
| Radix w/ per-component+accent splitter | 28–38 KB |

Compiled route confirms the pipeline (module imported **only** on pages where
the component mounts, then Vite-tree-shaken):
```js
import {Switch} from "@base-ui/react/switch"
import _rxcss_9968e39e from "$/styles/components/9968e39e/switch.module.css"
...jsx(Switch.Thumb, {className: _rxcss_9968e39e.thumb})
```

## B. Tailwind theme variant (full, browser-verified) — the RFC's recommendation

- `buispike/bui.py` — Base UI `switch`, `dialog` (Root/Trigger/Portal/Backdrop/
  Popup/Title/Description/Close) and a `button`, styled with **Tailwind utility
  classes** against a token theme, with `cn()` (clsx + tailwind-merge) so user
  `class_name` overrides win deterministically.
- `buispike/assets/theme.css` — the swappable token layer (`--primary-* →
  violet`, `--secondary-* → slate`, gray, light + `.dark`), generated from the
  real Radix scales.
- `buispike/buispike.py` — app exercising all of it: interactive switch (Python
  state round-trip), default + overridden buttons, a dialog, and dark mode
  (toggled on `<html>` so the portaled dialog is themed too).
- `buispike/shot.py` — Playwright driver that renders and exercises the app.

### Production CSS (gzipped), `reflex export`, zero Radix

| Asset | gz |
|---|---|
| `__reflex_global_styles` (Tailwind reset + all used utilities) | 5.07 KB |
| `theme.css` (entire violet/slate/gray token layer, light+dark) | 1.26 KB |
| **TOTAL** | **~6.3 KB** |

~13× smaller than full Radix (84 KB) for a **richer** page (dialog + switch +
4 buttons + dark mode + full token theme). The token layer can be trimmed to
only-used tokens; utilities already scale with usage.

### Browser verification (Playwright, headless Chromium)

`shot.py` → `ALL CHECKS PASSED`, screenshots in `/tmp/0{1,2,3}_*.png`:

- ✅ Renders faithfully (Radix-violet look) — `01_light.png`
- ✅ Switch **Python state round-trip** (On → Off → On via `rx.State`)
- ✅ User override wins via tailwind-merge (red `Destructive` button)
- ✅ Dark mode token-swap cascades to whole page — `02_dark.png`
- ✅ Base UI dialog opens (headless behavior, backdrop, focus) and is themed
  through the portal in dark mode — `03_dialog_dark.png` — and closes

## Why it works

The 28 KB Radix "floor" existed only because Radix ships its entire token+reset
system at runtime. With atomic CSS, Vite/Tailwind emit only what the page uses;
the token theme is a small, swappable layer. Both approaches collapse a page to
single-digit KB while keeping full control of the look. Tailwind is the RFC's
recommendation because user overrides are in the same language and merge
deterministically (`cn`/tailwind-merge + Tailwind's `@layer` order).

## What this does NOT prove

The remaining cost is unchanged: every component's *appearance* must be authored
as atomic classes to match the current look across all variants/sizes/states.
That re-skin — not the build plumbing — is the real migration effort. See
`rfcs/0001-base-ui-atomic-styling.md`.
