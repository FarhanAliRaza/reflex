# reflex-components-shadcn

A drop-in alternative to `reflex-components-radix` modeled after
[shadcn/ui](https://ui.shadcn.com/): each component compiles to plain HTML
elements (or, where behavior is required, headless `@radix-ui/react-*`
primitives) with **Tailwind utility class names** and CSS variables for
theming. There is no monolithic third-party stylesheet — the only CSS the
page ships is the Tailwind utilities the page actually uses, plus a small
theme-token preflight (~3 KB).

This is the architectural answer to the "Radix Themes ships ~600 KB CSS"
problem: shadcn-style components don't carry a design-system stylesheet,
so the bundle stays small even on heavy pages.

## Why a separate package?

`reflex-components-radix` (Radix Themes) and `reflex-components-shadcn`
have **the same Reflex public API** but two different compilation
targets. Most apps will pick one for the whole app; some will mix
(content pages on shadcn, dashboards on Radix Themes).

The two packages can be installed side by side. Choose per-app via
`rx.Config(component_library="shadcn")` or import directly from
`reflex_components_shadcn`.

## Status

v1 covers the components needed for content-heavy pages:

- `button` (variants: default / destructive / outline / secondary / ghost / link; sizes: default / sm / lg / icon)
- `card`, `card_header`, `card_title`, `card_description`, `card_content`, `card_footer`
- `heading.h1` ... `heading.h6`
- `text` / `paragraph`
- `link` (compiles to plain `<a>`)
- `code` / `code_block`
- `container`, `section`, `vstack`, `hstack`
- `separator`
- `badge` (variants: default / secondary / destructive / outline)

Interactive primitives backed by `@radix-ui/react-*` (dialog, tabs,
dropdown, popover, …) are tracked but not in v1.
