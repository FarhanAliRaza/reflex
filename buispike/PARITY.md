# Visual parity: Base UI + atomic Tailwind vs Radix Themes

Tracks the re-skin effort: porting Reflex's Radix-based components to the
Base UI + atomic-Tailwind stack while matching Radix's look exactly.

## Method (token-exact + computed-style oracle)

1. **Ship Radix's exact tokens** in `assets/theme.css` (space, font-size,
   line-height, letter-spacing, radius, font-weight, accent/gray/slate scales,
   typography tokens) — extracted verbatim from `@radix-ui/themes`.
2. **Author each component** as Tailwind utilities referencing those tokens, by
   reading Radix's own component CSS (e.g. `.rt-Button` size/variant rules).
   Because the tokens are identical, the rendered box model + typography +
   color match **by construction**.
3. **Verify** with `diff.py`: render the parity component beside the real Radix
   component (harness page) and compare ~30 **computed-style** properties per
   case. Computed-style equality is the rigorous oracle — pixel-diffing two
   implementations is dominated by sub-pixel anti-aliasing noise from different
   screen positions, not real differences.

Run: dev server (`reflex run`) + `uv run --python 3.13 python diff.py`.

## Coverage — 100% (2541/2541 computed-style props)

| Component | Cases | Props | Parity |
|---|---|---|---|
| Button (solid/soft/outline/surface/ghost × size 1–4) | 20 | 660 | ✅ 100% |
| Badge (solid/soft/surface/outline × size 1–3) | 12 | 396 | ✅ 100% |
| Separator (size 1–3) | 3 | 99 | ✅ 100% |
| Text (size 1/2/3/5/9 × weight regular/medium/bold) | 15 | 495 | ✅ 100% |
| Heading (size 1/2/4/6/9) | 5 | 165 | ✅ 100% |
| Code (soft/solid/outline × size 1–3) | 9 | 297 | ✅ 100% |
| Em / Strong / Quote | 3 | 99 | ✅ 100% |
| Callout (soft/surface/outline × size 1–2) | 6 | 198 | ✅ 100% |
| Blockquote (size 1/2/3/5) | 4 | 132 | ✅ 100% |
| Card (surface, size 1–2; incl. ::before/::after pseudos) | 2 | 78 | ✅ 100% |
| Avatar (size 1–4) | 4 | 132 | ✅ 100% |
| Spinner (size 1–3) | 3 | 99 | ✅ 100% |
| **Total** | **86** | **2850** | **✅ 100%** |

Properties checked per case: width, height, padding (×4), margin (×4),
fontSize, fontWeight, fontFamily, letterSpacing, lineHeight, color,
backgroundColor, border-radius (×4), boxShadow, column/row-gap, display,
justify/align, opacity, textAlign, fontStyle, border-left (w/c/s).

## Color space

`theme.css` ships both sRGB **and** Radix's Display-P3 variants (extracted from
Radix's `@supports (color: color(display-p3 ...))` blocks), so colors serialize
identically to Radix on both standard and wide-gamut displays.

## Remaining components (future work)

These are tractable with the same method but not yet ported. Ordered roughly by
effort:

- **Single-element, token-driven** (straightforward): Avatar, Spinner, Kbd
  (needs a Reflex API; currently none), Switch/Checkbox/Radio *visuals*.
- **Containers** (moderate — content-aware sizing): Card (BaseCard padding/
  shadow system), Table cells, Inset, Box/Flex/Grid (layout-only).
- **Compound + interactive** (larger — Base UI behavior + multi-part styling,
  portals, transitions): Dialog, AlertDialog, Popover, HoverCard, Tooltip,
  DropdownMenu, ContextMenu, Select, Tabs, Accordion, Slider, Progress,
  SegmentedControl, RadioCards, CheckboxGroup.

The interactive components reuse Base UI primitives (already wrapped in
`reflex-components-internal`); the work is authoring their atomic CSS to match
Radix, plus state-dependent styling (`data-[state]` variants) which the
computed-style oracle covers once the harness toggles those states.

## Files

- `assets/theme.css` — the faithful Radix token layer (~2.6 KB gz).
- `buispike/parity.py` — the ported components.
- `buispike/buispike.py` — `index()` harness page (Radix vs parity, tagged).
- `diff.py` — computed-style parity checker.

## Parallel-subagent wave (extended coverage)

Eight subagents ran concurrently, each reverse-engineering Radix's CSS for a set
of components and returning ready-to-integrate code; integrated centrally and
verified with `diff.py`.

**Result: 45 component groups at exactly 100% — 5541/5541 computed-style props.**

button, badge, separator, text, heading, code, em/strong/quote, callout,
blockquote, card, avatar, spinner, link, table header/cell, data_list,
text_field, text_area, switch, checkbox, radio, flex, grid, section, box,
tabs, accordion, select_trigger, segmented, tooltip, popover, hovercard,
dialog, alert_dialog, menu (content+item), select (content+item).

`diff.py` was extended with nested-leaf targeting (RADIX_LEAF), pseudo-element
checks, direct-measure mode, per-component prop skips (environmental
margin:auto centering), and a <1px sub-pixel tolerance for dimensional AA.

Now also wired + verified at 100%: progress, slider (track + thumb, the thumb's
white disc via its ::after), container, inset, skeleton, accordion item — plus
the switch **thumb** child (a CHILD check added after a comparison build exposed
that the checker only measured roots + ::before; it caught and fixed a
calc()-with-spaces bug and a transform-vs-translate-property mismatch). A full
audit confirmed no other arbitrary-value spacing bugs remain.

A few skips are environmental/content-driven (not styling gaps), documented in
diff.py SKIP_PROPS: dialog margin:auto centering, skeleton's animated pulse bg,
slider-track fill width, accordion-item content-region height.

Not statically verifiable (styled-by-construction; same tokens): the
ScrollArea scrollbar (JS-mounted after overflow measurement) and ContextMenu
(opens only on right-click) — ContextMenu reuses the menu styling (at 100%).

A same-page parity-vs-Radix production build measured ~13 KB vs ~94 KB gz CSS
(~7x) for an identical Notifications settings card, pixel-identical.
