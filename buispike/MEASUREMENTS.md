# Spike: Base UI (headless) + atomic CSS, end-to-end through Reflex

Goal: validate that a Reflex page built from a **headless Base UI** component
styled by a **per-component atomic CSS module** ships dramatically less CSS than
the Radix Themes runtime stylesheet — using the real compiler and the real Vite
production build, not estimates.

## What this app contains

- `buispike/baseui_switch.py` — a Base UI `Switch` (real `@base-ui/react/switch`
  package for behavior/a11y) wrapped as a `CSSModuleComponent`. Styling comes
  only from a co-located atomic module.
- `buispike/switch.module.css` — the switch's own rules (`.root` / `.thumb` +
  `data-checked` / `focus-visible` / `disabled`), `composes`-ing shared atoms.
- `buispike/_atoms.module.css` — shared atoms (copied once to `styles/_shared`).
- `buispike/buispike.py` — the app. Built once with both a `/radix` page
  (Radix Themes) and a `/baseui` page, then rebuilt with only `/baseui` to
  capture the fully-migrated end state.

## How it was measured

```
uv run --python 3.13 reflex export --frontend-only --no-zip
# CSS assets emitted under .web/build/client/assets/*.css ; gzip each
```

## Results (gzipped)

| Build | CSS shipped (gz) | Notes |
|---|---|---|
| Base UI + atomic CSS (fully migrated, **zero Radix**) | **~2.7 KB** | 406 B route chunk + 2.3 KB Tailwind reset |
| `_baseui_` route chunk alone | **406 B** | the entire switch: atoms + root + thumb + states |
| Radix Themes (implicit, full bundle) | **84 KB** | whole design-system runtime |
| Radix Themes w/ per-component+accent splitter | 28–38 KB | prior measurement on this branch |

~30× smaller than full Radix; ~10–14× smaller than the split.

## Why it works

The `CSSModuleComponent` mechanism emits the module's `import` **only on pages
where the component is mounted**; Vite then hashes/scopes/minifies and
tree-shakes everything not imported. The compiled route confirms the full
pipeline:

```js
import {Switch} from "@base-ui/react/switch"                                // headless behavior
import _rxcss_9968e39e from "$/styles/components/9968e39e/switch.module.css"  // per-page, tree-shaken
...jsx(Switch.Thumb, {className: _rxcss_9968e39e.thumb})                     // atomic class bound
```

The 28 KB Radix "floor" existed only because Radix ships its entire token+reset
system at runtime. Authoring per-component atomic CSS (CSS-Modules `composes`,
or Tailwind — Reflex's internal Base UI components already use the Tailwind
variant) collapses a page to single-digit KB while keeping full control of the
look.

## What this does NOT prove

The remaining cost is unchanged: every component's *appearance* must be authored
as atomic CSS to match the current look. That re-skin — not the build plumbing —
is the real migration effort.
