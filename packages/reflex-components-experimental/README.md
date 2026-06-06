# reflex-components-experimental

Experimental Reflex component layer: **Base UI behaviour + atomic Tailwind**,
authored against Radix's exact design tokens so the rendered look matches Radix
Themes pixel-for-pixel while shipping a fraction of the CSS (~7x less on a real
page). See `rfcs/0001-base-ui-atomic-styling.md`.

Status: **experimental** — API may change. Enable via
`rxe.ExperimentalThemePlugin()` in `rxconfig.py` (alongside `TailwindV4Plugin`).

## Two layers

- **Static / presentational** (`components.py`): plain HTML elements styled with
  token Tailwind utilities — typography, layout, cards, badges, inputs, tables.
  No JS behaviour needed; native HTML semantics.
- **Accessible interactive** (`interactive.py`): the same token styling layered
  on [Base UI](https://base-ui.com) (`@base-ui/react`) headless parts, so
  switches, checkboxes, radios, tabs, sliders, menus, dialogs, selects, popovers,
  tooltips, accordions, etc. ship real ARIA roles/states, keyboard navigation and
  focus management. State styling (e.g. a checked switch) is driven by Base UI
  `data-[checked]` / `data-[selected]` Tailwind variants rather than being
  hard-coded, so the look tracks live state. Verified with axe-core (0 violations)
  and a headless-browser ARIA/keyboard sweep.

```python
import reflex as rx
import reflex_components_experimental as rxe

def index():
    return rxe.card(
        rxe.heading("Hello", size="6"),
        rxe.switch(default_checked=True),            # role=switch, keyboard-toggle
        rxe.tabs.root(                                # arrow-key tab navigation
            rxe.tabs.list(rxe.tabs.tab("One", "1"), rxe.tabs.tab("Two", "2")),
            rxe.tabs.panel(rxe.text("Panel one"), value="1"),
            default_value="1",
        ),
        size="2",
    )
```

Simple controls keep a flat callable API (`rxe.switch`, `rxe.checkbox`,
`rxe.slider`, `rxe.progress`); compound widgets are grouped namespaces of styled
Base UI parts (`rxe.dialog.root/popup`, `rxe.menu.item`, `rxe.select.trigger`,
`rxe.tabs.tab`, ...).
