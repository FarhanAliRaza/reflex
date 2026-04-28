import reflex as rx

from agent_files import AgentFilesPlugin

config = rx.Config(
    app_name="reflex_docs",
    frontend_path="/docs",
    frontend_packages=[
        "tailwindcss-animated",
    ],
    frontend_inspector="dev",
    telemetry_enabled=False,
    plugins=[
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.SitemapPlugin(trailing_slash="always"),
        AgentFilesPlugin(),
    ],
)
