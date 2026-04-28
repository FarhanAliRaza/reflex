"""Tests for inspector plugin templates."""

from __future__ import annotations

import json

from reflex_base.compiler import inspector_plugins, templates
from reflex_base.inspector.shortcut import parse_shortcut


def test_vite_plugin_includes_serve_guard():
    plugin = inspector_plugins.vite_plugin_template(
        parse_shortcut("alt+x"), force=False
    )
    assert "/__reflex/inspector.js" in plugin
    assert "apply: 'serve'" in plugin
    assert "configureServer" in plugin
    assert "reflexEditorMiddleware" in plugin


def test_vite_plugin_force_drops_serve_guard():
    plugin = inspector_plugins.vite_plugin_template(parse_shortcut("alt+x"), force=True)
    assert "apply: 'serve'" not in plugin


def test_vite_plugin_embeds_shortcut_literal():
    plugin = inspector_plugins.vite_plugin_template(
        parse_shortcut("cmd+shift+i"), force=False
    )
    payload = {"key": "i", "alt": False, "ctrl": False, "meta": True, "shift": True}
    assert json.dumps(payload) in plugin


def test_astro_integration_dev_only_guard():
    integration = inspector_plugins.astro_integration_template(
        parse_shortcut("alt+x"), force=False
    )
    assert "command !== 'dev'" in integration
    assert "astro:server:setup" in integration
    assert "astro:config:setup" in integration


def test_astro_integration_force_drops_dev_guard():
    integration = inspector_plugins.astro_integration_template(
        parse_shortcut("alt+x"), force=True
    )
    assert "command !== 'dev'" not in integration


def test_vite_config_includes_plugin_when_enabled():
    config = templates.vite_config_template(
        base="/",
        hmr=False,
        force_full_reload=False,
        experimental_hmr=False,
        sourcemap=False,
        inspector="dev",
    )
    assert "reflexInspectorPlugin" in config
    assert './reflex-inspector-plugin.js"' in config


def test_vite_config_omits_plugin_when_off():
    config = templates.vite_config_template(
        base="/",
        hmr=False,
        force_full_reload=False,
        experimental_hmr=False,
        sourcemap=False,
        inspector="off",
    )
    assert "reflexInspectorPlugin" not in config
    assert "reflex-inspector-plugin.js" not in config
