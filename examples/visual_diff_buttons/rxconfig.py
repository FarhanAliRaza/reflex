"""Visual diff harness — Radix Themes Button vs shadcn Button.

Run with the React Router target so the side-by-side page matches what
production users see today; the shadcn column proves the new
architecture renders the same pixels using only Tailwind utilities.
"""

import reflex as rx

config = rx.Config(
    app_name="visual_diff_buttons",
    telemetry_enabled=False,
    plugins=[
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(accent_color="violet", radius="medium"),
        ),
    ],
)
