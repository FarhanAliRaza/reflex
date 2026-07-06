# reflex-components-experimental

Experimental Reflex component layer: **Base UI behaviour + atomic Tailwind**,
authored against Radix's exact design tokens. Computed styles match Radix
Themes exactly (5541/5541 properties across 45 component groups, verified under
the default violet/slate/medium light theme) while shipping a fraction of the
CSS (~7x less on a real page). See
[`rfcs/0001-base-ui-atomic-styling.md`](../../rfcs/0001-base-ui-atomic-styling.md)
at the repo root.

Status: **experimental** — API may change. Enable via
`rxe.ExperimentalThemePlugin()` in `rxconfig.py` (alongside `TailwindV4Plugin`).

## Theming

The plugin mirrors `rx.theme`'s options and generates the token stylesheet at
compile time from vendored Radix scale data (`radix_colors/`) — only the chosen
accent + gray scales ship (~4 KB gz including light, dark, and Display-P3
variants):

```python
plugins = [
    rx.plugins.TailwindV4Plugin(),
    rxe.ExperimentalThemePlugin(
        accent_color="iris",  # any Radix accent color
        gray_color="sand",  # gray / mauve / slate / sage / olive / sand
        radius="large",  # none / small / medium / large / full
        scaling="105%",  # 90% / 95% / 100% / 105% / 110%
    ),
]
```

`--accent-*` / `--gray-*` (and the semantic `--primary-*` / `--secondary-*`)
resolve to the chosen scales the same way Radix Themes maps
`accentColor`/`grayColor`, so every component recolors from the one setting.
Invalid options fail at config load with the valid choices listed. Re-vendor
the scale data after a Radix bump with `scripts/vendor_radix_colors.py`.

## Two layers

- **Static / presentational** (`components/`, `layout/`, `typography/`): plain
  HTML elements styled with token Tailwind utilities — typography, layout, cards,
  badges, inputs, tables. No JS behaviour needed; native HTML semantics.
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
        rxe.switch(default_checked=True),  # role=switch, keyboard-toggle
        rxe.tabs.root(  # arrow-key tab navigation
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
