"""M1 gate: the Rust-registered construction schema classifies identically.

``CompilerSession.register_component_schema`` ships the Python-built
``ConstructionSchema`` across the boundary; ``class_schema_classify``
exposes the Rust-side classification for differential testing against
``ConstructionSchema.classify``.
"""

from __future__ import annotations

import pytest
from reflex_base.components.component import Component
from reflex_base.event import EventHandler, no_args_event_spec
from reflex_base.vars.base import Var

import reflex as rx
from reflex.compiler.session import CompilerSession

pytest.importorskip("reflex_compiler_rust._native")


class _RustSchemaProbe(Component):
    tag = "RustSchemaProbe"
    library = "rust-schema-probe"

    var_prop: Var[str]
    plain_prop: str
    on_custom: EventHandler[no_args_event_spec]


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


def _sample_classes() -> list[type[Component]]:
    from reflex_components_core.el.elements.typography import Div
    from reflex_components_radix.themes.components.switch import Switch

    return [
        _RustSchemaProbe,
        Switch,
        *(
            type(factory())
            for factory in (
                rx.box,
                rx.text,
                rx.button,
                rx.fragment,
            )
        ),
        Div,
        type(rx.markdown("x")),
        type(rx.icon_button("plus")),
        type(rx.input(value="")),
        type(rx.upload()),
        type(rx.form()),
    ]


def test_classify_matches_python_schema():
    session = CompilerSession()
    for cls in _sample_classes():
        session.register_component_schema(cls)
        schema = cls._construction_schema()
        names = (
            set(cls.get_fields())
            | set(cls.get_event_triggers())
            | set(cls.get_props())
            | set(_SYNTHETIC_NAMES)
        )
        for name in names:
            assert session.class_schema_classify(cls, name) == schema.classify(name), (
                f"{cls.__module__}.{cls.__name__}.{name}"
            )


def test_unregistered_class_reports_no_schema():
    session = CompilerSession()

    class Unregistered(Component):
        tag = "Unregistered"
        library = "rust-schema-probe"

    assert not session.class_schema_registered(Unregistered)
    assert session.class_schema_classify(Unregistered, "anything") is None
    assert session.class_schema_rename_props(Unregistered) is None


def test_registration_is_per_session_and_idempotent():
    session = CompilerSession()
    other = CompilerSession()
    session.register_component_schema(_RustSchemaProbe)
    session.register_component_schema(_RustSchemaProbe)
    assert session.class_schema_registered(_RustSchemaProbe)
    assert not other.class_schema_registered(_RustSchemaProbe)
    assert session.class_schema_classify(_RustSchemaProbe, "var_prop") == "prop_var"


def test_rename_props_round_trip():
    from reflex_components_radix.themes.components.switch import Switch

    session = CompilerSession()
    session.register_component_schema(Switch)
    round_tripped = session.class_schema_rename_props(Switch)
    assert round_tripped is not None
    assert dict(round_tripped) == dict(Switch._construction_schema().rename_props)
    assert ("onChange", "onCheckedChange") in round_tripped
    session.register_component_schema(_RustSchemaProbe)
    assert session.class_schema_rename_props(_RustSchemaProbe) == []
