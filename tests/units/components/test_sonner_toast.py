"""Tests for the Sonner toast component wrapper."""

from reflex_base.components.component import NoSSRComponent
from reflex_components_sonner.toast import Toaster


def test_toaster_is_no_ssr_component():
    """The Sonner toaster must not render during Astro SSR."""
    assert issubclass(Toaster, NoSSRComponent)

    toaster = Toaster.create()
    dynamic_import = toaster._get_dynamic_imports()

    assert "ClientSide" in dynamic_import
    assert "mod.Toaster" in dynamic_import
