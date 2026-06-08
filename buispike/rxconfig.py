import reflex as rx
import reflex_components_experimental as rxe

config = rx.Config(
    app_name="buispike",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rxe.ExperimentalThemePlugin(),
    ],
)
