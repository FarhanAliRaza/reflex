# RFC 0001 — Base UI + atomic Tailwind theme as the default component system

- Status: Draft
- Branch: `claude/unstyled-primitives-css-modules-nRbTL`
- Spike: `buispike/` (+ `buispike/MEASUREMENTS.md`)

## 1. Summary

Replace Radix Themes as Reflex's default component system with **headless Base
UI primitives styled by an atomic Tailwind v4 theme**. Behavior/accessibility
come from `@base-ui/react`; appearance comes from Tailwind utility classes that
reference a swappable semantic-token theme. User overrides are first-class via
their own Tailwind classes, merged deterministically with `tailwind-merge`.

The payoff, measured end-to-end through the real Vite build:

| Page | CSS shipped (gz) |
|---|---|
| Base UI + atomic Tailwind — simple page (dialog + switch + 4 buttons) | **~6.3 KB** |
| Base UI + atomic Tailwind — real page (Notifications card, full site build) | **~13 KB** |
| Radix Themes today (full runtime bundle) | **84–94 KB** |
| Radix w/ per-component+accent splitter (prior work on this branch, reverted) | 28–38 KB |

~7–13× smaller than full Radix — and still ~2–6× below the ~28 KB gz floor the
tree-shaking approach bottomed out at — while keeping full control of the look
and a clean user-override story.

## 2. Motivation

Radix Themes ships its **entire design system at runtime** — every design
token, the full element reset, and every component's CSS — in one ~84 KB-gz
stylesheet, regardless of what a page uses. Prior work on this branch tree-shook
that to ~28–38 KB per page (per-component + per-accent chunks), but hit a hard
floor: ~28 KB gz of tokens + reset + root setup is **universal** to the Radix
look and cannot be split away.

The only way below that floor is to stop shipping a whole design system and
instead **emit only the CSS a page actually uses**. Atomic CSS (Tailwind, or
compile-time atomic engines) does exactly this. The spike confirmed a real
Reflex page can ship single-digit-KB CSS this way.

## 3. Current state (what already exists)

This is not a greenfield migration — most of the pieces are already in the repo:

- **Headless layer**: `reflex-components-internal` already wraps ~30 Base UI
  components (`accordion`, `dialog`, `select`, `tabs`, `tooltip`, `menu`,
  `popover`, `slider`, `switch`, `checkbox`, `toggle`, `navigation_menu`, …)
  via `BaseUIComponent` (`@base-ui/react`).
- **Atomic styling**: those components are already styled with Tailwind utility
  classes, e.g. `switch.py`:
  ```python
  ROOT = (
      "relative flex h-5 w-8 rounded-full bg-secondary-4 … data-[checked]:bg-primary-9 …"
  )
  ```
- **Theme tokens**: `reflex-site-shared/.../styles/globals.css` defines the
  semantic-token theme via Tailwind v4 `@theme` — `--primary-9: var(--violet-9)`,
  `--secondary-*`, `--info/success/warning/destructive-*`, radius, fonts,
  shadows, text scales, animations — plus dark mode through
  `@custom-variant dark (&:where(.dark, .dark *))` and `.dark` overrides.
- **Override merging**: `CoreComponent.set_class_name` merges defaults with user
  classes through `cn()` (`clsx-for-tailwind` / `tailwind-merge`):
  ```python
  props["class_name"] = cn(default_class_name, props_class_name)
  ```
- **Build**: `TailwindV4Plugin` is enabled by default in new apps; the frontend
  builds with Vite.
- **Deprecation already in motion**: implicit Radix Themes enablement was
  deprecated in 0.9.0 with removal slated for 1.0
  (`reflex-components-radix/.../plugin.py`).

What's missing is making this the **default `rx.*` surface**, promoting the
theme tokens out of `reflex-site-shared` into a shippable plugin, and a
documented override contract.

## 4. Proposed architecture

Four layers, each independently swappable:

```
┌─ Behavior ─────────  @base-ui/react primitives (headless, a11y)
├─ Component styles ─  Tailwind utility class strings on each part
│                       (e.g. "rounded-full bg-primary-9 data-[checked]:…")
├─ Theme tokens ─────  @theme { --color-primary-9: var(--primary-9); … }
│                       --primary-9: var(--violet-9)   ← semantic → scale
└─ User overrides ───  class_name="bg-red-500"  →  cn(default, user)  →  tailwind-merge
```

- **Components** are authored once with Tailwind utilities against *semantic*
  tokens (`primary`, `secondary`, `info`, `success`, `warning`, `destructive`),
  never raw scales. Variants/sizes are conditional class strings (the
  shadcn/ui pattern), not a prebuilt utility matrix.
- **The theme** is the single place colors/radius/fonts are bound. Re-theming =
  re-point `--primary-9` to a different scale; the whole library recolors.
- **Vite + Tailwind v4** emit only the utilities actually present in the
  generated JSX → per-page CSS scales with usage, not with library size.

## 5. The override guarantee (why this is robust)

Two complementary mechanisms ensure a user's own Tailwind always wins:

1. **Pre-render merge** — `cn(default, user)` runs `tailwind-merge`, which
   removes a default utility when the user supplies a conflicting one
   (`bg-primary-9` + `bg-red-500` → `bg-red-500`). Conflicts never reach CSS.

2. **Cascade layering** — for non-utility component CSS (e.g. any CSS-module
   base we keep), Tailwind v4's layer order makes utilities win regardless of
   source order:
   ```css
   @layer theme, base, components, utilities;
   ```
   A user's utility in the `utilities` layer beats component CSS in `components`
   deterministically — no `!important`, no import-order fragility.

This is the crux of choosing Tailwind (see §7): the override language and the
component language are the same, so merges are well-defined.

## 6. Theming & dark mode

- **Theme**: ship `globals.css`'s `@theme` block as a Tailwind plugin asset
  (promoted out of `reflex-site-shared`). Expose an `rx`-level API to repoint
  semantic tokens (e.g. `primary="iris"`) by overriding `--primary-*` in
  `:root`.
- **Dark mode**: `@custom-variant dark (&:where(.dark, .dark *))` + a `.dark`
  class toggled on the root (Reflex already has `rx.color_mode`). Tokens whose
  values differ in dark are overridden under `.dark`.
- The Radix color *scales* (`--violet-9`, …) remain the value source, so the
  palette and perceptual quality are preserved — only the delivery changes.

## 7. Why Tailwind, not StyleX or CSS Modules

The hard requirement — **users override components with their own Tailwind** —
eliminates the alternatives, because cross-system overrides have no clean merge:

| Internal system | User overrides with Tailwind |
|---|---|
| **Tailwind** | ✅ Same language; `tailwind-merge` resolves conflicts pre-render. Already wired. |
| **StyleX** | ⚠️ StyleX's predictable merge only applies among `stylex.props()` calls. A foreign Tailwind class competes by stylesheet order/specificity. Also needs a compiler plugin and authoring styles as JS objects; StyleX wants to own the cascade. |
| **CSS Modules** | ⚠️ `.root{…}` vs `.bg-red-500{…}` are equal specificity → winner is bundle order. Needs `@layer` discipline to be safe. Smallest output, weakest override ergonomics. |

CSS Modules (this branch's `CSSModuleComponent`) remains useful for complex,
non-overridable structural CSS behind the `@layer components` guard, but
Tailwind is the default authoring surface.

## 8. Migration plan

**Phase 0 — foundation (small):**
- Promote `globals.css` `@theme` tokens into a shippable theme (Tailwind plugin
  asset) owned by the component package, not the site.
- Add an explicit `RadixThemesPlugin` opt-in (already exists) and document it.

**Phase 1 — parity audit (medium):**
- Inventory `rx.*` against the ~30 existing `reflex-components-internal` Base UI
  components. Produce a gap list (missing components, missing props, look
  deltas vs current Radix output).
- Pixel-diff each Base UI component against its Radix equivalent; close gaps in
  the Tailwind class strings.

**Phase 2 — default surface (medium):**
- Route `rx.button`, `rx.switch`, `rx.dialog`, … to the Base UI + Tailwind
  implementations behind a config flag (default off → on).
- Keep Radix components importable under an explicit namespace for one release.

**Phase 3 — deprecate Radix Themes (aligned with existing 1.0 removal):**
- Radix implicit enablement is already deprecated (0.9.0 → removal 1.0). Land
  the Base UI default before 1.0; ship Radix as opt-in only after.

**Out of scope:** changing the public `rx.*` Python API. The goal is a
swap of the rendering/styling backend behind the same component API.

## 9. Measurements (from the spike)

Real `reflex export` + Vite production builds (`buispike/MEASUREMENTS.md`):

- Simple page (dialog + switch + 4 buttons + dark mode): **5.07 KB gz** global
  styles + **1.26 KB gz** token theme = **~6.3 KB gz**, vs **84 KB gz** Radix
  (~13×).
- Same-page comparison (identical Notifications card, full multi-component
  build): **~13 KB gz** vs **~94 KB gz** Radix (~7×).
- Compiled output verified correct: real `@base-ui/react` subpath imports,
  per-page CSS tree-shaken by Vite, atomic classes bound to the elements.
- An earlier CSS-module-per-component variant measured **~2.7 KB gz** total for
  a single-widget page (406 B route chunk); its source was superseded by the
  Tailwind approach and removed, so that figure is historical, not reproducible
  from this branch.

## 10. Risks & open questions

- **Look fidelity is the real cost.** Matching Radix exactly across every
  component/variant/state is the bulk of the work; class strings can drift.
  Mitigation: pixel-diff tests per component.
- **Tailwind utility soup in Python.** Long class strings are hard to review.
  Mitigation: `ClassNames` constants per component (already the pattern);
  consider extracting recurring clusters into `@utility` shortcuts.
- **`@base-ui/react` is pre-1.0** (the internal pkg pins `1.5.0`; npm also
  publishes `@base-ui-components/react@1.0.0-rc.0`). Pin and track.
- **Theme-swap API surface.** How much theming to expose (single accent vs full
  token override) is an open design question.
- **Forms/SSR/portals** (dialog, select) need explicit integration testing
  under the Base UI implementations.

## 11. Recommendation

Adopt **Base UI + atomic Tailwind v4** as the default. It is the only option
that (a) breaks the 28 KB Radix floor to single-digit KB, (b) preserves the
look via the existing Radix-scale-backed token theme, and (c) gives users a
clean, deterministic override path in the same language they already use. Most
of the implementation already exists; the work is parity + theming + flipping
the default, not a from-scratch build.
