"""Differential tests for ``ConstructionSchema`` vs ``_post_init`` (arena M1).

The schema is the static mirror of ``_post_init``'s per-kwarg classification.
These tests pin the two against each other in both directions: a literal
transcription of ``_post_init``'s branch order swept across every loaded
Component class, plus behavioral spot checks that drive ``create()`` and
assert each kwarg landed where the schema said it would.
"""

from __future__ import annotations

import contextlib
import importlib
import pkgutil

import pytest
from reflex_base.components.component import Component, ConstructionSchema
from reflex_base.constants.compiler import SpecialAttributes
from reflex_base.event import EventHandler, no_args_event_spec
from reflex_base.vars.base import Var


class SchemaProbe(Component):
    """Probe class exercising every kwarg classification branch."""

    tag = "SchemaProbe"
    library = "schema-probe"

    var_prop: Var[str]
    plain_prop: str
    on_custom: EventHandler[no_args_event_spec]


def _post_init_reference(cls: type[Component], name: str) -> str:
    """Literal transcription of ``_post_init``'s kwarg branch order.

    Deliberately duplicates the production loop structure (component.py)
    so a drift in ``ConstructionSchema`` shows up as a diff against the
    construction semantics, not against the schema's own sources.

    Args:
        cls: The component class.
        name: The kwarg name.

    Returns:
        The classification category string.
    """
    fields = cls.get_fields()
    triggers = cls.get_event_triggers()
    props = cls.get_props()
    if name.startswith("on_") and name not in triggers and name not in props:
        return "invalid"
    if name in triggers:
        return "event_trigger"
    if name in props:
        field = fields.get(name)
        is_var = field is not None and field.type_origin is Var
        return "prop_var" if is_var else "prop"
    if name in fields:
        return "field"
    if SpecialAttributes.is_special(name):
        return "special_attr"
    return "style"


_SYNTHETIC_NAMES = (
    "on_unknown_event",
    "on_",
    "onclick",
    "data_testid",
    "data-testid",
    "aria_label",
    "aria-label",
    "background_color",
    "totally_unknown",
)


def _name_universe(cls: type[Component]) -> set[str]:
    return (
        set(cls.get_fields())
        | set(cls.get_event_triggers())
        | set(cls.get_props())
        | set(_SYNTHETIC_NAMES)
    )


_SWEEP_PACKAGES = (
    "reflex_components_core",
    "reflex_components_radix",
    "reflex_components_lucide",
    "reflex_components_markdown",
    "reflex_components_sonner",
    "reflex_components_code",
)


def _all_component_subclasses() -> set[type[Component]]:
    for package_name in _SWEEP_PACKAGES:
        package = importlib.import_module(package_name)
        for module in pkgutil.walk_packages(
            package.__path__, prefix=package.__name__ + "."
        ):
            # Optional-dependency modules may fail to import standalone;
            # the class-count floor below guards against over-skipping.
            with contextlib.suppress(Exception):
                importlib.import_module(module.name)
    seen: set[type[Component]] = set()
    stack: list[type[Component]] = [Component]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return seen


def test_schema_matches_post_init_across_all_loaded_components():
    classes = _all_component_subclasses()
    assert len(classes) > 200, "component sweep unexpectedly small"
    for cls in classes:
        schema = cls._construction_schema()
        for name in _name_universe(cls):
            assert schema.classify(name) == _post_init_reference(cls, name), (
                f"{cls.__module__}.{cls.__name__}.{name}"
            )


def test_schema_is_cached_per_class():
    assert SchemaProbe._construction_schema() is SchemaProbe._construction_schema()

    class Sub(SchemaProbe):
        sub_prop: Var[int]

    sub_schema = Sub._construction_schema()
    assert sub_schema is not SchemaProbe._construction_schema()
    assert sub_schema.classify("sub_prop") == "prop_var"
    assert SchemaProbe._construction_schema().classify("sub_prop") == "style"


def test_schema_dataclass_shape():
    schema = SchemaProbe._construction_schema()
    assert isinstance(schema, ConstructionSchema)
    assert schema.props["var_prop"] is True
    assert schema.props["plain_prop"] is False
    assert "on_custom" in schema.triggers
    assert "on_custom" not in schema.props
    assert "children" in schema.base_fields
    assert "style" in schema.base_fields


def test_var_prop_is_literalvar_wrapped():
    comp = SchemaProbe.create(var_prop="x")
    assert SchemaProbe._construction_schema().classify("var_prop") == "prop_var"
    assert isinstance(comp.__dict__["var_prop"], Var)


def test_plain_prop_stored_raw():
    comp = SchemaProbe.create(plain_prop="x")
    assert SchemaProbe._construction_schema().classify("plain_prop") == "prop"
    assert comp.__dict__["plain_prop"] == "x"
    assert not isinstance(comp.__dict__["plain_prop"], Var)


def test_event_triggers_land_in_event_triggers():
    import reflex as rx

    comp = SchemaProbe.create(
        on_custom=rx.console_log("a"), on_click=rx.console_log("b")
    )
    schema = SchemaProbe._construction_schema()
    assert schema.classify("on_custom") == "event_trigger"
    assert schema.classify("on_click") == "event_trigger"
    assert set(comp.event_triggers) == {"on_custom", "on_click"}


def test_unknown_on_name_raises():
    import reflex as rx

    assert SchemaProbe._construction_schema().classify("on_bogus") == "invalid"
    with pytest.raises(ValueError, match="on_bogus"):
        SchemaProbe.create(on_bogus=rx.console_log("a"))


def test_special_attrs_land_in_custom_attrs():
    comp = SchemaProbe.create(data_testid="t", aria_label="l")
    schema = SchemaProbe._construction_schema()
    assert schema.classify("data_testid") == "special_attr"
    assert schema.classify("aria_label") == "special_attr"
    assert comp.custom_attrs["data-testid"] == "t"
    assert comp.custom_attrs["aria-label"] == "l"


def test_unknown_name_lands_in_style():
    comp = SchemaProbe.create(background_color="red")
    assert SchemaProbe._construction_schema().classify("background_color") == "style"
    # Style normalization may camelize the key; values may be Var-wrapped.
    assert "background_color" in comp.style or "backgroundColor" in comp.style


def test_base_field_kwarg_sets_attr():
    comp = SchemaProbe.create(custom_attrs={"x": "1"})
    assert SchemaProbe._construction_schema().classify("custom_attrs") == "field"
    assert comp.custom_attrs == {"x": "1"}


def test_rename_props_carried():
    from reflex_components_radix.themes.components.switch import Switch

    schema = Switch._construction_schema()
    # _rename_props is merged across the MRO at class creation; the own
    # entry must be present alongside any inherited ones.
    assert schema.rename_props["onChange"] == "onCheckedChange"
    assert dict(schema.rename_props) == dict(Switch._rename_props)
    assert SchemaProbe._construction_schema().rename_props == {}
