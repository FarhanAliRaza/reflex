# reflex-components-experimental

Experimental Reflex component layer: **Base UI behaviour + atomic Tailwind**,
authored against Radix's exact design tokens so the rendered look matches Radix
Themes pixel-for-pixel while shipping a fraction of the CSS (~7x less on a real
page). See `rfcs/0001-base-ui-atomic-styling.md`.

Status: **experimental** — API may change. Enable via
`rxe.ExperimentalThemePlugin()` in `rxconfig.py` (alongside `TailwindV4Plugin`).
