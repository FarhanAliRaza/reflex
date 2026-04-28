"""Tests for inspector plugin templates."""

from __future__ import annotations

from reflex_base.compiler import inspector_plugins, templates


def test_vite_plugin_is_dev_only():
    plugin = inspector_plugins.vite_plugin_template()
    assert "apply: 'serve'" in plugin
    assert "configureServer" in plugin
    assert "reflexEditorMiddleware" in plugin


def test_vite_plugin_omits_editor_when_unset():
    plugin = inspector_plugins.vite_plugin_template()
    assert "REFLEX_EDITOR" not in plugin


def test_vite_plugin_threads_editor_through():
    plugin = inspector_plugins.vite_plugin_template(editor="code -g")
    assert 'process.env.REFLEX_EDITOR ||= "code -g";' in plugin


def test_vite_config_includes_plugin_when_enabled():
    config = templates.vite_config_template(
        base="/",
        hmr=False,
        force_full_reload=False,
        experimental_hmr=False,
        sourcemap=False,
        inspector=True,
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
        inspector=False,
    )
    assert "reflexInspectorPlugin" not in config
    assert "reflex-inspector-plugin.js" not in config
