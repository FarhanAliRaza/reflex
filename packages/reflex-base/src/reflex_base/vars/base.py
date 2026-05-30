"""Collection of base classes."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import datetime
import functools
import inspect
import json
import math
import re
import string
import uuid
import warnings
from abc import ABCMeta
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from dataclasses import _MISSING_TYPE, MISSING
from decimal import Decimal
from importlib.util import find_spec
from types import CodeType, FunctionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Generic,
    Literal,
    NoReturn,
    ParamSpec,
    Protocol,
    TypeGuard,
    TypeVar,
    cast,
    get_args,
    get_type_hints,
    is_typeddict,
    overload,
)

from rich.markup import escape
from typing_extensions import LiteralString, dataclass_transform, override
from typing_extensions import TypeVar as TypeVarExt

from reflex_base import constants
from reflex_base.constants.state import FIELD_MARKER
from reflex_base.utils import console, exceptions, format, imports, serializers, types
from reflex_base.utils.compat import annotations_from_namespace
from reflex_base.utils.decorator import once
from reflex_base.utils.exceptions import (
    ComputedVarSignatureError,
    PrimitiveUnserializableToJSONError,
    UntypedComputedVarError,
    VarAttributeError,
    VarDependencyError,
    VarTypeError,
)
from reflex_base.utils.format import format_state_name
from reflex_base.utils.imports import ImportDict, ImportVar
from reflex_base.utils.types import (
    GenericType,
    Self,
    _isinstance,
    get_origin,
    has_args,
    safe_issubclass,
    unionize,
)

if TYPE_CHECKING:
    from reflex.state import BaseState
    from reflex_base.constants.colors import Color

    from .color import LiteralColorVar


VAR_TYPE = TypeVar("VAR_TYPE", covariant=True)
OTHER_VAR_TYPE = TypeVar("OTHER_VAR_TYPE")
STRING_T = TypeVar("STRING_T", bound=str)
LITERAL_STRING_T = TypeVar("LITERAL_STRING_T", bound=LiteralString)
SEQUENCE_TYPE = TypeVar("SEQUENCE_TYPE", bound=Sequence)

warnings.filterwarnings("ignore", message="fields may not start with an underscore")

_PYDANTIC_VALIDATE_VALUES = "__pydantic_validate_values__"


def _pydantic_validator(*args, **kwargs):
    return None


@dataclasses.dataclass(
    eq=False,
    frozen=True,
)
class VarSubclassEntry:
    """Entry for a Var subclass."""

    var_subclass: type[Var]
    to_var_subclass: type[ToOperation]
    python_types: tuple[GenericType, ...]


_var_subclasses: list[VarSubclassEntry] = []
_var_literal_subclasses: list[tuple[type[LiteralVar], VarSubclassEntry]] = []


# VarData is now the Rust-backed RustVarData (hard cutover, no Python impl).
from reflex_compiler_rust._native import RustLiteralVar, RustVar  # noqa: E402
from reflex_compiler_rust._native import RustVarData as VarData


def _rust_var_classify(var_type: GenericType) -> type:
    """Return the typed ``Var`` subclass that ``var_type`` classifies as.

    Mirrors ``Var.guess_type``'s ``_var_subclasses`` registry matching, but
    returns the matched class instead of converting a var — the single source of
    truth for the ``isinstance`` bridge (so a ``RustVar`` is recognized as the
    right typed ``Var`` based on its ``_var_type``).

    Args:
        var_type: The var's Python type.

    Returns:
        The matched typed ``Var`` subclass (``Var`` when nothing matches).
    """
    if var_type is None:
        return NoneVar
    if var_type is NoReturn or var_type is Any:
        return Var
    var_type = types.value_inside_optional(var_type)
    if var_type is Any:
        return Var
    fixed_type = get_origin(var_type) or var_type
    if fixed_type in types.UnionTypes:
        fixed_inner = [
            get_origin(t) or t
            for t in (types.value_inside_optional(a) for a in get_args(var_type))
        ]
        for entry in reversed(_var_subclasses):
            if all(safe_issubclass(t, entry.python_types) for t in fixed_inner):
                return entry.var_subclass
        return ObjectVar if can_use_in_object_var(var_type) else Var
    if fixed_type is Literal:
        fixed_type = unionize(*(type(arg) for arg in get_args(var_type)))
    if not isinstance(fixed_type, type):
        return Var
    if fixed_type is None:
        return NoneVar
    for entry in reversed(_var_subclasses):
        if safe_issubclass(fixed_type, entry.python_types):
            return entry.var_subclass
    return ObjectVar if can_use_in_object_var(fixed_type) else Var


# The standard typed Var classes whose entire behavior the unified ``RustVar``
# reproduces (operators + methods dispatched off ``_var_type``). For these,
# ``guess_type`` is identity. Any *other* registered subclass (e.g.
# ``ReflexURLCastedVar``) carries bespoke rendering/properties and must be
# produced as its own casted instance.
_STANDARD_VAR_CLASS_NAMES = frozenset({
    "Var",
    "NumberVar",
    "BooleanVar",
    "StringVar",
    "ArrayVar",
    "ObjectVar",
    "NoneVar",
    "DateTimeVar",
    "ColorVar",
    "FunctionVar",
    "BuilderFunctionVar",
    "RangeVar",
})


def _rust_guess_type(var: RustVar) -> Any:
    """Resolve a ``RustVar`` to its typed form (the bridge for ``guess_type``).

    Standard typed classes are reproduced by ``RustVar`` itself, so the var is
    returned unchanged. A custom registered subclass (carrying bespoke
    behavior, e.g. ``ReflexURLCastedVar``) is produced as its casted instance
    via the registry, so its custom rendering/properties survive.

    Args:
        var: The Rust-backed var to resolve.

    Returns:
        The var itself, or its custom casted-subclass instance.
    """
    matched = _rust_var_classify(var._var_type)
    if matched.__name__ in _STANDARD_VAR_CLASS_NAMES:
        return var
    for entry in _var_subclasses:
        if entry.var_subclass is matched:
            return entry.to_var_subclass.create(value=var, _var_type=var._var_type)
    return var


def _literal_pair_for(var_subclass: type) -> type | None:
    """Return the ``LiteralVar`` subclass paired with ``var_subclass``, if any.

    Args:
        var_subclass: A typed ``Var`` subclass (e.g. ``NumberVar``).

    Returns:
        The paired literal subclass (e.g. ``LiteralNumberVar``) or ``None``.
    """
    for literal_subclass, entry in _var_literal_subclasses:
        if entry.var_subclass is var_subclass:
            return literal_subclass
    return None


def _rust_var_isinstance(instance: RustVar, cls: type) -> bool:
    """Whether a ``RustVar`` should be considered an instance of ``cls``.

    Classifies the var's ``_var_type`` against the typed-``Var`` registry. For a
    ``LiteralVar``-family target, the var must additionally be a
    ``RustLiteralVar``.

    Args:
        instance: The Rust-backed var.
        cls: The (Var-family) class being tested.

    Returns:
        ``True`` if ``instance`` matches ``cls``.
    """
    matched = _rust_var_classify(instance._var_type)
    if type.__subclasscheck__(LiteralVar, cls):
        if not isinstance(instance, RustLiteralVar):
            return False
        literal = _literal_pair_for(matched)
        return literal is not None and type.__subclasscheck__(cls, literal)
    return type.__subclasscheck__(cls, matched)


def _decode_var_immutable(value: str) -> tuple[VarData | None, str]:
    """Decode the state name from a formatted var.

    Args:
        value: The value to extract the state name from.

    Returns:
        The extracted state name and the value without the state name.
    """
    var_datas = []
    if isinstance(value, str):
        # fast path if there is no encoded VarData
        if constants.REFLEX_VAR_OPENING_TAG not in value:
            return None, value

        offset = 0

        # Find all tags.
        while m := _decode_var_pattern.search(value):
            start, end = m.span()
            value = value[:start] + value[end:]

            serialized_data = m.group(1)

            if serialized_data.isnumeric() or (
                serialized_data[0] == "-" and serialized_data[1:].isnumeric()
            ):
                # This is a global immutable var.
                var = _global_vars[int(serialized_data)]
                var_data = var._get_all_var_data()

                if var_data is not None:
                    var_datas.append(var_data)
            offset += end - start

    return VarData.merge(*var_datas) if var_datas else None, value


def can_use_in_object_var(cls: GenericType) -> bool:
    """Check if the class can be used in an ObjectVar.

    Args:
        cls: The class to check.

    Returns:
        Whether the class can be used in an ObjectVar.
    """
    if types.is_union(cls):
        return all(can_use_in_object_var(t) for t in types.get_args(cls))
    return (
        isinstance(cls, type)
        and not safe_issubclass(cls, Var)
        and serializers.can_serialize(cls, dict)
    )


_BASE_VAR: list[type] = []


class MetaclassVar(ABCMeta):
    """Metaclass for the Var class.

    Subclasses ``ABCMeta`` so the Rust ``Var`` / ``LiteralVar`` can be
    registered as virtual subclasses (``Var.register(RustVar)``) — making
    ``isinstance(rust_var, Var)`` a native, cached check with no per-call
    bridge. Typed-category membership (``StringVar``/``ArrayVar``/…), which
    depends on a Rust var's runtime ``_var_type`` rather than its class, is
    answered by the explicit :func:`var_isinstance` helper instead.
    """

    def __call__(cls, *args, **kwargs):  # noqa: D102
        if _BASE_VAR and cls is _BASE_VAR[0]:
            # Supply the dataclass `Any` default when no `_var_type` is given
            # (RustVar keeps an explicitly-passed `None`, which pyo3 cannot
            # distinguish from absent on its own).
            if len(args) < 2 and "_var_type" not in kwargs:
                kwargs["_var_type"] = Any
            return RustVar(*args, **kwargs)
        return super().__call__(*args, **kwargs)

    def __setattr__(cls, name: str, value: Any):
        """Set an attribute on the class.

        Args:
            name: The name of the attribute.
            value: The value of the attribute.
        """
        super().__setattr__(
            name, value if name != _PYDANTIC_VALIDATE_VALUES else _pydantic_validator
        )


def var_isinstance(value: Any, cls: type) -> bool:
    """Whether ``value`` is a var that classifies as the typed ``Var`` ``cls``.

    ``isinstance(x, Var)`` / ``isinstance(x, LiteralVar)`` are native (the Rust
    classes are registered virtual subclasses). This helper covers the
    *typed-category* questions (``isinstance(x, StringVar)`` etc.) that depend on
    a Rust var's runtime ``_var_type`` — a Rust var is classified by its
    ``_var_type``; any other object falls back to a plain ``isinstance``.

    Args:
        value: The object to test.
        cls: The typed ``Var`` subclass to test against.

    Returns:
        Whether ``value`` matches ``cls``.
    """
    if isinstance(value, RustVar):
        return _rust_var_isinstance(value, cls)
    return isinstance(value, cls)


@dataclasses.dataclass(
    eq=False,
    frozen=True,
)
class Var(Generic[VAR_TYPE], metaclass=MetaclassVar):
    """Base class for immutable vars."""

    # The name of the var.
    _js_expr: str = dataclasses.field()

    # The type of the var.
    _var_type: types.GenericType = dataclasses.field(default=Any)

    # Extra metadata associated with the Var
    _var_data: VarData | None = dataclasses.field(default=None)

    def __str__(self) -> str:
        """String representation of the var. Guaranteed to be a valid Javascript expression.

        Returns:
            The name of the var.
        """
        return self._js_expr

    @property
    def _var_is_local(self) -> bool:
        """Whether this is a local javascript variable.

        Returns:
            False
        """
        return False

    @property
    def _var_is_string(self) -> bool:
        """Whether the var is a string literal.

        Returns:
            False
        """
        return False

    def __init_subclass__(
        cls,
        python_types: tuple[GenericType, ...] | GenericType = types.Unset(),
        default_type: GenericType = types.Unset(),
        **kwargs,
    ):
        """Initialize the subclass.

        Args:
            python_types: The python types that the var represents.
            default_type: The default type of the var. Defaults to the first python type.
            **kwargs: Additional keyword arguments.
        """
        super().__init_subclass__(**kwargs)

        if python_types or default_type:
            python_types = (
                (python_types if isinstance(python_types, tuple) else (python_types,))
                if python_types
                else ()
            )

            default_type = default_type or (python_types[0] if python_types else Any)

            @dataclasses.dataclass(
                eq=False,
                frozen=True,
                slots=True,
            )
            class ToVarOperation(ToOperation, cls):
                """Base class of converting a var to another var type."""

                _original: Var = dataclasses.field(
                    default=Var(_js_expr="null", _var_type=None),
                )

                _default_var_type: ClassVar[GenericType] = default_type

            new_to_var_operation_name = f"{cls.__name__.removesuffix('Var')}CastedVar"
            ToVarOperation.__qualname__ = (
                ToVarOperation.__qualname__.removesuffix(ToVarOperation.__name__)
                + new_to_var_operation_name
            )
            ToVarOperation.__name__ = new_to_var_operation_name

            _var_subclasses.append(VarSubclassEntry(cls, ToVarOperation, python_types))

    def __post_init__(self):
        """Post-initialize the var.

        Raises:
            TypeError: If _js_expr is not a string.
        """
        if not isinstance(self._js_expr, str):
            msg = f"Expected _js_expr to be a string, got value {self._js_expr!r} of type {type(self._js_expr).__name__}"
            raise TypeError(msg)

        if self._var_data is not None and not isinstance(self._var_data, VarData):
            msg = f"Expected _var_data to be a VarData, got value {self._var_data!r} of type {type(self._var_data).__name__}"
            raise TypeError(msg)

        # Decode any inline Var markup and apply it to the instance
        var_data_, js_expr_ = _decode_var_immutable(self._js_expr)

        if var_data_ or js_expr_ != self._js_expr:
            self.__init__(
                _js_expr=js_expr_,
                _var_type=self._var_type,
                _var_data=VarData.merge(self._var_data, var_data_),
            )

    def __hash__(self) -> int:
        """Define a hash function for the var.

        Returns:
            The hash of the var.
        """
        return hash((self._js_expr, self._var_type, self._var_data))

    def _get_all_var_data(self) -> VarData | None:
        """Get all VarData associated with the Var.

        Returns:
            The VarData of the components and all of its children.
        """
        return self._var_data

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Deepcopy the var.

        Args:
            memo: The memo dictionary to use for the deepcopy.

        Returns:
            A deepcopy of the var.
        """
        return self

    def equals(self, other: Var) -> bool:
        """Check if two vars are equal.

        Args:
            other: The other var to compare.

        Returns:
            Whether the vars are equal.
        """
        return (
            self._js_expr == other._js_expr
            and self._var_type == other._var_type
            and self._get_all_var_data() == other._get_all_var_data()
        )

    @overload
    def _replace(
        self,
        _var_type: type[OTHER_VAR_TYPE],
        merge_var_data: VarData | None = None,
        **kwargs: Any,
    ) -> Var[OTHER_VAR_TYPE]: ...

    @overload
    def _replace(
        self,
        _var_type: GenericType | None = None,
        merge_var_data: VarData | None = None,
        **kwargs: Any,
    ) -> Self: ...

    def _replace(
        self,
        _var_type: GenericType | None = None,
        merge_var_data: VarData | None = None,
        **kwargs: Any,
    ) -> Self | Var:
        """Make a copy of this Var with updated fields.

        Args:
            _var_type: The new type of the Var.
            merge_var_data: VarData to merge into the existing VarData.
            **kwargs: Var fields to update.

        Returns:
            A new Var with the updated fields overwriting the corresponding fields in this Var.

        Raises:
            TypeError: If _var_is_local, _var_is_string, or _var_full_name_needs_state_prefix is not None.
        """
        if kwargs.get("_var_is_local", False) is not False:
            msg = "The _var_is_local argument is not supported for Var."
            raise TypeError(msg)

        if kwargs.get("_var_is_string", False) is not False:
            msg = "The _var_is_string argument is not supported for Var."
            raise TypeError(msg)

        if kwargs.get("_var_full_name_needs_state_prefix", False) is not False:
            msg = "The _var_full_name_needs_state_prefix argument is not supported for Var."
            raise TypeError(msg)
        value_with_replaced = dataclasses.replace(
            self,
            _var_type=_var_type or self._var_type,
            _var_data=VarData.merge(
                kwargs.get("_var_data", self._var_data), merge_var_data
            ),
            **kwargs,
        )

        if (js_expr := kwargs.get("_js_expr")) is not None:
            object.__setattr__(value_with_replaced, "_js_expr", js_expr)

        return value_with_replaced

    @overload
    @classmethod
    def create(  # pyright: ignore[reportOverlappingOverload]
        cls,
        value: NoReturn,
        _var_data: VarData | None = None,
    ) -> Var[Any]: ...

    @overload
    @classmethod
    def create(  # pyright: ignore[reportOverlappingOverload]
        cls,
        value: bool,
        _var_data: VarData | None = None,
    ) -> LiteralBooleanVar: ...

    @overload
    @classmethod
    def create(
        cls,
        value: int,
        _var_data: VarData | None = None,
    ) -> LiteralNumberVar[int]: ...

    @overload
    @classmethod
    def create(
        cls,
        value: float,
        _var_data: VarData | None = None,
    ) -> LiteralNumberVar[float]: ...

    @overload
    @classmethod
    def create(
        cls,
        value: Decimal,
        _var_data: VarData | None = None,
    ) -> LiteralNumberVar[Decimal]: ...

    @overload
    @classmethod
    def create(  # pyright: ignore [reportOverlappingOverload]
        cls,
        value: Color,
        _var_data: VarData | None = None,
    ) -> LiteralColorVar: ...

    @overload
    @classmethod
    def create(  # pyright: ignore [reportOverlappingOverload]
        cls,
        value: LITERAL_STRING_T,
        _var_data: VarData | None = None,
    ) -> LiteralStringVar[LITERAL_STRING_T]: ...

    @overload
    @classmethod
    def create(  # pyright: ignore [reportOverlappingOverload]
        cls,
        value: STRING_T,
        _var_data: VarData | None = None,
    ) -> StringVar[STRING_T]: ...

    @overload
    @classmethod
    def create(  # pyright: ignore[reportOverlappingOverload]
        cls,
        value: None,
        _var_data: VarData | None = None,
    ) -> LiteralNoneVar: ...

    @overload
    @classmethod
    def create(
        cls,
        value: MAPPING_TYPE,
        _var_data: VarData | None = None,
    ) -> LiteralObjectVar[MAPPING_TYPE]: ...

    @overload
    @classmethod
    def create(
        cls,
        value: SEQUENCE_TYPE,
        _var_data: VarData | None = None,
    ) -> LiteralArrayVar[SEQUENCE_TYPE]: ...

    @overload
    @classmethod
    def create(
        cls,
        value: OTHER_VAR_TYPE,
        _var_data: VarData | None = None,
    ) -> Var[OTHER_VAR_TYPE]: ...

    @classmethod
    def create(
        cls,
        value: OTHER_VAR_TYPE,
        _var_data: VarData | None = None,
    ) -> Var[OTHER_VAR_TYPE]:
        """Create a var from a value.

        Args:
            value: The value to create the var from.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The var.
        """
        # If the value is already a var, do nothing.
        if isinstance(value, Var):
            return value

        return LiteralVar.create(value, _var_data=_var_data)

    def __format__(self, format_spec: str) -> str:
        """Format the var into a Javascript equivalent to an f-string.

        Args:
            format_spec: The format specifier (Ignored for now).

        Returns:
            The formatted var.
        """
        hashed_var = hash(self)

        _global_vars[hashed_var] = self

        # Encode the _var_data into the formatted output for tracking purposes.
        return f"{constants.REFLEX_VAR_OPENING_TAG}{hashed_var}{constants.REFLEX_VAR_CLOSING_TAG}{self._js_expr}"

    @overload
    def to(self, output: type[str]) -> StringVar: ...  # pyright: ignore[reportOverlappingOverload]

    @overload
    def to(self, output: type[bool]) -> BooleanVar: ...

    @overload
    def to(self, output: type[int]) -> NumberVar[int]: ...

    @overload
    def to(self, output: type[float]) -> NumberVar[float]: ...

    @overload
    def to(self, output: type[Decimal]) -> NumberVar[Decimal]: ...

    @overload
    def to(
        self,
        output: type[SEQUENCE_TYPE],
    ) -> ArrayVar[SEQUENCE_TYPE]: ...

    @overload
    def to(
        self,
        output: type[MAPPING_TYPE],
    ) -> ObjectVar[MAPPING_TYPE]: ...

    @overload
    def to(
        self, output: type[ObjectVar], var_type: type[VAR_INSIDE]
    ) -> ObjectVar[VAR_INSIDE]: ...

    @overload
    def to(
        self, output: type[ObjectVar], var_type: None = None
    ) -> ObjectVar[VAR_TYPE]: ...

    @overload
    def to(self, output: VAR_SUBCLASS, var_type: None = None) -> VAR_SUBCLASS: ...

    @overload
    def to(
        self,
        output: type[OUTPUT] | types.GenericType,
        var_type: types.GenericType | None = None,
    ) -> OUTPUT: ...

    def to(
        self,
        output: type[OUTPUT] | types.GenericType,
        var_type: types.GenericType | None = None,
    ) -> Var:
        """Convert the var to a different type.

        Args:
            output: The output type.
            var_type: The type of the var.

        Returns:
            The converted var.
        """
        fixed_output_type = get_origin(output) or output

        # If the first argument is a python type, we map it to the corresponding Var type.
        for var_subclass in _var_subclasses[::-1]:
            if fixed_output_type in var_subclass.python_types or safe_issubclass(
                fixed_output_type, var_subclass.python_types
            ):
                return self.to(var_subclass.var_subclass, output)

        if fixed_output_type is None:
            return get_to_operation(NoneVar).create(self)  # pyright: ignore [reportReturnType]

        # Handle fixed_output_type being Base or a dataclass.
        if can_use_in_object_var(output):
            return self.to(ObjectVar, output)

        if isinstance(output, type):
            for var_subclass in _var_subclasses[::-1]:
                if safe_issubclass(output, var_subclass.var_subclass):
                    current_var_type = self._var_type
                    if current_var_type is Any:
                        new_var_type = var_type
                    else:
                        new_var_type = var_type or current_var_type
                    return var_subclass.to_var_subclass.create(  # pyright: ignore [reportReturnType]
                        value=self, _var_type=new_var_type
                    )

            # If we can't determine the first argument, we just replace the _var_type.
            if not safe_issubclass(output, Var) or var_type is None:
                return dataclasses.replace(
                    self,
                    _var_type=output,
                )

        # We couldn't determine the output type to be any other Var type, so we replace the _var_type.
        if var_type is not None:
            return dataclasses.replace(
                self,
                _var_type=var_type,
            )

        return self

    @overload
    def guess_type(self: Var[NoReturn]) -> Var[Any]: ...  # pyright: ignore [reportOverlappingOverload]

    @overload
    def guess_type(self: Var[str]) -> StringVar: ...

    @overload
    def guess_type(self: Var[bool]) -> BooleanVar: ...

    @overload
    def guess_type(self: Var[int] | Var[float] | Var[int | float]) -> NumberVar: ...

    @overload
    def guess_type(self) -> Self: ...

    def guess_type(self) -> Var:
        """Guesses the type of the variable based on its `_var_type` attribute.

        Returns:
            Var: The guessed type of the variable.

        Raises:
            TypeError: If the type is not supported for guessing.
        """
        var_type = self._var_type
        if var_type is None:
            return self.to(None)
        if var_type is NoReturn:
            return self.to(Any)

        var_type = types.value_inside_optional(var_type)

        if var_type is Any:
            return self

        fixed_type = get_origin(var_type) or var_type

        if fixed_type in types.UnionTypes:
            inner_types = get_args(var_type)
            non_optional_inner_types = [
                types.value_inside_optional(inner_type) for inner_type in inner_types
            ]
            fixed_inner_types = [
                get_origin(inner_type) or inner_type
                for inner_type in non_optional_inner_types
            ]

            for var_subclass in _var_subclasses[::-1]:
                if all(
                    safe_issubclass(t, var_subclass.python_types)
                    for t in fixed_inner_types
                ):
                    return self.to(var_subclass.var_subclass, self._var_type)

            if can_use_in_object_var(var_type):
                return self.to(ObjectVar, self._var_type)

            return self

        if fixed_type is Literal:
            args = get_args(var_type)
            fixed_type = unionize(*(type(arg) for arg in args))

        if not isinstance(fixed_type, type):
            msg = f"Unsupported type {var_type} for guess_type."
            raise TypeError(msg)

        if fixed_type is None:
            return self.to(None)

        for var_subclass in _var_subclasses[::-1]:
            if safe_issubclass(fixed_type, var_subclass.python_types):
                return self.to(var_subclass.var_subclass, self._var_type)

        if can_use_in_object_var(fixed_type):
            return self.to(ObjectVar, self._var_type)

        return self

    @staticmethod
    def _get_setter_name_for_name(
        name: str,
    ) -> str:
        """Get the name of the var's generated setter function.

        Args:
            name: The name of the var.

        Returns:
            The name of the setter function.
        """
        return constants.SETTER_PREFIX + name

    def _get_setter(self, name: str) -> Callable[[BaseState, Any], None]:
        """Get the var's setter function.

        Args:
            name: The name of the var.

        Returns:
            A function that that creates a setter for the var.
        """
        setter_name = Var._get_setter_name_for_name(name)

        def setter(state: Any, value: Any):
            """Get the setter for the var.

            Args:
                state: The state within which we add the setter function.
                value: The value to set.
            """
            if self._var_type in [int, float]:
                try:
                    value = self._var_type(value)
                    setattr(state, name, value)
                except ValueError:
                    console.debug(
                        f"{type(state).__name__}.{self._js_expr}: Failed conversion of {value!s} to '{self._var_type.__name__}'. Value not set.",
                    )
            else:
                setattr(state, name, value)

        setter.__annotations__["value"] = self._var_type

        setter.__qualname__ = setter_name

        return setter

    def _var_set_state(self, state: type[BaseState] | str) -> Self:
        """Set the state of the var.

        Args:
            state: The state to set.

        Returns:
            The var with the state set.
        """
        formatted_state_name = (
            state
            if isinstance(state, str)
            else format_state_name(state.get_full_name())
        )

        return StateOperation.create(  # pyright: ignore [reportReturnType]
            formatted_state_name,
            self,
            _var_data=VarData.merge(
                VarData.from_state(state, self._js_expr), self._var_data
            ),
        ).guess_type()

    def __eq__(self, other: Var | Any) -> BooleanVar:
        """Check if the current variable is equal to the given variable.

        Args:
            other (Var | Any): The variable to compare with.

        Returns:
            BooleanVar: A BooleanVar object representing the result of the equality check.
        """
        return equal_operation(self, other)

    def __ne__(self, other: Var | Any) -> BooleanVar:
        """Check if the current object is not equal to the given object.

        Parameters:
            other (Var | Any): The object to compare with.

        Returns:
            BooleanVar: A BooleanVar object representing the result of the comparison.
        """
        return ~equal_operation(self, other)

    def bool(self) -> BooleanVar:
        """Convert the var to a boolean.

        Returns:
            The boolean var.
        """
        return boolify(self)

    def is_none(self) -> BooleanVar:
        """Check if the var is None.

        Returns:
            A BooleanVar object representing the result of the check.
        """
        return ~is_not_none_operation(self)

    def is_not_none(self) -> BooleanVar:
        """Check if the var is not None.

        Returns:
            A BooleanVar object representing the result of the check.
        """
        return is_not_none_operation(self)

    def __and__(
        self, other: Var[OTHER_VAR_TYPE] | Any
    ) -> Var[VAR_TYPE | OTHER_VAR_TYPE]:
        """Perform a logical AND operation on the current instance and another variable.

        Args:
            other: The variable to perform the logical AND operation with.

        Returns:
            A `BooleanVar` object representing the result of the logical AND operation.
        """
        return and_operation(self, other)

    def __rand__(
        self, other: Var[OTHER_VAR_TYPE] | Any
    ) -> Var[VAR_TYPE | OTHER_VAR_TYPE]:
        """Perform a logical AND operation on the current instance and another variable.

        Args:
            other: The variable to perform the logical AND operation with.

        Returns:
            A `BooleanVar` object representing the result of the logical AND operation.
        """
        return and_operation(other, self)

    def __or__(
        self, other: Var[OTHER_VAR_TYPE] | Any
    ) -> Var[VAR_TYPE | OTHER_VAR_TYPE]:
        """Perform a logical OR operation on the current instance and another variable.

        Args:
            other: The variable to perform the logical OR operation with.

        Returns:
            A `BooleanVar` object representing the result of the logical OR operation.
        """
        return or_operation(self, other)

    def __ror__(
        self, other: Var[OTHER_VAR_TYPE] | Any
    ) -> Var[VAR_TYPE | OTHER_VAR_TYPE]:
        """Perform a logical OR operation on the current instance and another variable.

        Args:
            other: The variable to perform the logical OR operation with.

        Returns:
            A `BooleanVar` object representing the result of the logical OR operation.
        """
        return or_operation(other, self)

    def __invert__(self) -> BooleanVar:
        """Perform a logical NOT operation on the current instance.

        Returns:
            A `BooleanVar` object representing the result of the logical NOT operation.
        """
        return ~self.bool()

    def to_string(self, use_json: bool = True) -> StringVar:
        """Convert the var to a string.

        Args:
            use_json: Whether to use JSON stringify. If False, uses Object.prototype.toString.

        Returns:
            The string var.
        """
        return (
            JSON_STRINGIFY.call(self).to(StringVar)
            if use_json
            else PROTOTYPE_TO_STRING.call(self).to(StringVar)
        )

    def _as_ref(self) -> Var:
        """Get a reference to the var.

        Returns:
            The reference to the var.
        """
        return Var(
            _js_expr=f"refs[{Var.create(str(self))}]",
            _var_data=VarData(
                imports={
                    f"$/{constants.Dirs.STATE_PATH}": [imports.ImportVar(tag="refs")]
                }
            ),
        ).to(str)

    def js_type(self) -> StringVar:
        """Returns the javascript type of the object.

        This method uses the `typeof` function from the `FunctionStringVar` class
        to determine the type of the object.

        Returns:
            StringVar: A string variable representing the type of the object.
        """
        type_of = FunctionStringVar("typeof")
        return type_of.call(self).to(StringVar)

    def _without_data(self):
        """Create a copy of the var without the data.

        Returns:
            The var without the data.
        """
        return dataclasses.replace(self, _var_data=None)

    def _decode(self) -> Any:
        """Decode Var as a python value.

        Note that Var with state set cannot be decoded python-side and will be
        returned as full_name.

        Returns:
            The decoded value or the Var name.
        """
        if isinstance(self, LiteralVar):
            return self._var_value
        try:
            return json.loads(str(self))
        except ValueError:
            return str(self)

    @property
    def _var_state(self) -> str:
        """Compat method for getting the state.

        Returns:
            The state name associated with the var.
        """
        var_data = self._get_all_var_data()
        return var_data.state if var_data else ""

    @overload
    @classmethod
    def range(cls, stop: int | NumberVar, /) -> ArrayVar[Sequence[int]]: ...

    @overload
    @classmethod
    def range(
        cls,
        start: int | NumberVar,
        end: int | NumberVar,
        step: int | NumberVar = 1,
        /,
    ) -> ArrayVar[Sequence[int]]: ...

    @classmethod
    def range(
        cls,
        first_endpoint: int | NumberVar,
        second_endpoint: int | NumberVar | None = None,
        step: int | NumberVar | None = None,
    ) -> ArrayVar[Sequence[int]]:
        """Create a range of numbers.

        Args:
            first_endpoint: The end of the range if second_endpoint is not provided, otherwise the start of the range.
            second_endpoint: The end of the range.
            step: The step of the range.

        Returns:
            The range of numbers.
        """
        return RustVar.range(first_endpoint, second_endpoint, step)

    if not TYPE_CHECKING:

        def __getitem__(self, key: Any) -> Var:
            """Get the item from the var.

            Args:
                key: The key to get.

            Raises:
                UntypedVarError: If the var type is Any.
                TypeError: If the var type is Any.

            # noqa: DAR101 self
            """
            if self._var_type is Any:
                raise exceptions.UntypedVarError(
                    self,
                    f"access the item '{key}'",
                )
            msg = f"Var of type {self._var_type} does not support item access."
            raise TypeError(msg)

        def __getattr__(self, name: str):
            """Get an attribute of the var.

            Args:
                name: The name of the attribute.

            Raises:
                VarAttributeError: If the attribute does not exist.
                UntypedVarError: If the var type is Any.
                TypeError: If the var type is Any.

            # noqa: DAR101 self
            """
            if name.startswith("_"):
                msg = f"Attribute {name} not found."
                raise VarAttributeError(msg)

            if name == "contains":
                msg = f"Var of type {self._var_type} does not support contains check."
                raise TypeError(msg)
            if name == "reverse":
                msg = "Cannot reverse non-list var."
                raise TypeError(msg)

            if self._var_type is Any:
                raise exceptions.UntypedVarError(
                    self,
                    f"access the attribute '{name}'",
                )

            msg = f"The State var {escape(self._js_expr)} of type {escape(str(self._var_type))} has no attribute '{name}' or may have been annotated wrongly."
            raise VarAttributeError(msg)

        def __bool__(self) -> bool:
            """Raise exception if using Var in a boolean context.

            Raises:
                VarTypeError: when attempting to bool-ify the Var.

            # noqa: DAR101 self
            """
            msg = (
                f"Cannot convert Var {str(self)!r} to bool for use with `if`, `and`, `or`, and `not`. "
                "Instead use `rx.cond` and bitwise operators `&` (and), `|` (or), `~` (invert)."
            )
            raise VarTypeError(msg)

        def __iter__(self) -> Any:
            """Raise exception if using Var in an iterable context.

            Raises:
                VarTypeError: when attempting to iterate over the Var.

            # noqa: DAR101 self
            """
            msg = f"Cannot iterate over Var {str(self)!r}. Instead use `rx.foreach`."
            raise VarTypeError(msg)

        def __contains__(self, _: Any) -> Var:
            """Override the 'in' operator to alert the user that it is not supported.

            Raises:
                VarTypeError: the operation is not supported

            # noqa: DAR101 self
            """
            msg = (
                "'in' operator not supported for Var types, use Var.contains() instead."
            )
            raise VarTypeError(msg)


_BASE_VAR.append(Var)


OUTPUT = TypeVar("OUTPUT", bound=Var)

VAR_SUBCLASS = TypeVar("VAR_SUBCLASS", bound=Var)
VAR_INSIDE = TypeVar("VAR_INSIDE")


class ToOperation:
    """A var operation that converts a var to another type."""

    def __getattr__(self, name: str) -> Any:
        """Get an attribute of the var.

        Args:
            name: The name of the attribute.

        Returns:
            The attribute of the var.
        """
        if var_isinstance(self, ObjectVar) and name != "_js_expr":
            return ObjectVar.__getattr__(self, name)
        return getattr(self._original, name)

    def __post_init__(self):
        """Post initialization."""
        object.__delattr__(self, "_js_expr")

    def __hash__(self) -> int:
        """Calculate the hash value of the object.

        Returns:
            int: The hash value of the object.
        """
        return hash(self._original)

    def _get_all_var_data(self) -> VarData | None:
        """Get all the var data.

        Returns:
            The var data.
        """
        return VarData.merge(
            self._original._get_all_var_data(),
            self._var_data,
        )

    @classmethod
    def create(
        cls,
        value: Var,
        _var_type: GenericType | None = None,
        _var_data: VarData | None = None,
    ):
        """Create a ToOperation.

        Args:
            value: The value of the var.
            _var_type: The type of the Var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The ToOperation.
        """
        return cls(
            _js_expr="",  # pyright: ignore [reportCallIssue]
            _var_data=_var_data,  # pyright: ignore [reportCallIssue]
            _var_type=_var_type or cls._default_var_type,  # pyright: ignore [reportCallIssue, reportAttributeAccessIssue]
            _original=value,  # pyright: ignore [reportCallIssue]
        )


class LiteralVar(Var[VAR_TYPE]):
    """Base class for immutable literal vars."""

    def __init_subclass__(cls, **kwargs):
        """Initialize the subclass.

        Args:
            **kwargs: Additional keyword arguments.

        Raises:
            TypeError: If the LiteralVar subclass does not have a corresponding Var subclass.
        """
        super().__init_subclass__(**kwargs)

        bases = cls.__bases__

        bases_normalized = [
            base if isinstance(base, type) else get_origin(base) for base in bases
        ]

        possible_bases = [
            base
            for base in bases_normalized
            if safe_issubclass(base, Var) and base != LiteralVar
        ]

        if not possible_bases:
            msg = f"LiteralVar subclass {cls} must have a base class that is a subclass of Var and not LiteralVar."
            raise TypeError(msg)

        var_subclasses = [
            var_subclass
            for var_subclass in _var_subclasses
            if var_subclass.var_subclass in possible_bases
        ]

        if not var_subclasses:
            msg = f"LiteralVar {cls} must have a base class annotated with `python_types`."
            raise TypeError(msg)

        if len(var_subclasses) != 1:
            msg = f"LiteralVar {cls} must have exactly one base class annotated with `python_types`."
            raise TypeError(msg)

        var_subclass = var_subclasses[0]

        # Remove the old subclass, happens because __init_subclass__ is called twice
        # for each subclass. This is because of __slots__ in dataclasses.
        for var_literal_subclass in list(_var_literal_subclasses):
            if var_literal_subclass[1] is var_subclass:
                _var_literal_subclasses.remove(var_literal_subclass)

        _var_literal_subclasses.append((cls, var_subclass))

    @classmethod
    def _create_literal_var(
        cls,
        value: Any,
        _var_data: VarData | None = None,
    ) -> Var:
        """Create a var from a value.

        Args:
            value: The value to create the var from.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The var.

        Raises:
            TypeError: If the value is not a supported type for LiteralVar.
        """
        if isinstance(value, Var):
            if _var_data is None:
                return value
            return value._replace(merge_var_data=_var_data)

        # Scalars (incl. strings, with f-string marker decode + folding) and
        # plain list/dict literals (with element-type inference, recursive json,
        # and embedded-var var_data aggregation) are produced by the Rust literal
        # var — byte-identical to the Python literal subclasses. Exotic types
        # (datetime/Color/range/serializer-backed/dataclasses) and non-exact
        # types (int/str subclasses, tuples, sets, custom Mappings) stay on the
        # Python dispatch below.
        if type(value) in (
            bool,
            int,
            float,
            str,
            type(None),
            list,
            dict,
            tuple,
            set,
            Decimal,
            datetime.datetime,
            datetime.date,
        ):
            return RustLiteralVar.create(value, _var_data=_var_data)

        for literal_subclass, var_subclass in _var_literal_subclasses[::-1]:
            if isinstance(value, var_subclass.python_types):
                return literal_subclass.create(value, _var_data=_var_data)

        if (
            (as_var_method := getattr(value, "_as_var", None)) is not None
            and callable(as_var_method)
            and isinstance((resulting_var := as_var_method()), Var)
        ):
            return resulting_var

        from reflex_base.event import EventHandler
        from reflex_base.utils.format import get_event_handler_parts

        if isinstance(value, EventHandler):
            return Var(_js_expr=".".join(filter(None, get_event_handler_parts(value))))

        serialized_value = serializers.serialize(value)
        if serialized_value is not None:
            if isinstance(serialized_value, (Mapping, str)):
                return RustLiteralVar.create(
                    serialized_value,
                    _var_type=type(value),
                    _var_data=_var_data,
                )
            return LiteralVar.create(serialized_value, _var_data=_var_data)

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return RustLiteralVar.create(
                {
                    k.name: (None if callable(v := getattr(value, k.name)) else v)
                    for k in dataclasses.fields(value)
                },
                _var_type=type(value),
                _var_data=_var_data,
            )

        if isinstance(value, range):
            return RustVar.range(value.start, value.stop, value.step)

        msg = f"Unsupported type {type(value)} for LiteralVar. Tried to create a LiteralVar from {value}."
        raise TypeError(msg)

    if not TYPE_CHECKING:
        create = _create_literal_var

    def __post_init__(self):
        """Post-initialize the var."""

    @classmethod
    def _get_all_var_data_without_creating_var(
        cls,
        value: Any,
    ) -> VarData | None:
        return cls.create(value)._get_all_var_data()

    @classmethod
    def _get_all_var_data_without_creating_var_dispatch(
        cls,
        value: Any,
    ) -> VarData | None:
        """Get all the var data without creating a var.

        Args:
            value: The value to get the var data from.

        Returns:
            The var data or None.

        Raises:
            TypeError: If the value is not a supported type for LiteralVar.
        """
        if isinstance(value, Var):
            return value._get_all_var_data()

        for literal_subclass, var_subclass in _var_literal_subclasses[::-1]:
            if isinstance(value, var_subclass.python_types):
                return literal_subclass._get_all_var_data_without_creating_var(value)

        if (
            (as_var_method := getattr(value, "_as_var", None)) is not None
            and callable(as_var_method)
            and isinstance((resulting_var := as_var_method()), Var)
        ):
            return resulting_var._get_all_var_data()

        from reflex_base.event import EventHandler
        from reflex_base.utils.format import get_event_handler_parts

        if isinstance(value, EventHandler):
            return Var(
                _js_expr=".".join(filter(None, get_event_handler_parts(value)))
            )._get_all_var_data()

        serialized_value = serializers.serialize(value)
        if serialized_value is not None:
            if isinstance(serialized_value, Mapping):
                return LiteralObjectVar._get_all_var_data_without_creating_var(
                    serialized_value
                )
            if isinstance(serialized_value, str):
                return LiteralStringVar._get_all_var_data_without_creating_var(
                    serialized_value
                )
            return LiteralVar._get_all_var_data_without_creating_var_dispatch(
                serialized_value
            )

        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return LiteralObjectVar._get_all_var_data_without_creating_var({
                k.name: (None if callable(v := getattr(value, k.name)) else v)
                for k in dataclasses.fields(value)
            })

        if isinstance(value, range):
            return None

        msg = f"Unsupported type {type(value)} for LiteralVar. Tried to create a LiteralVar from {value}."
        raise TypeError(msg)

    @property
    def _var_value(self) -> Any:
        msg = "LiteralVar subclasses must implement the _var_value property."
        raise NotImplementedError(msg)

    def json(self) -> str:
        """Serialize the var to a JSON string.

        Raises:
            NotImplementedError: If the method is not implemented.
        """
        msg = "LiteralVar subclasses must implement the json method."
        raise NotImplementedError(msg)


@serializers.serializer
def serialize_literal(value: LiteralVar):
    """Serialize a Literal type.

    Args:
        value: The Literal to serialize.

    Returns:
        The serialized Literal.
    """
    return value._var_value


@serializers.serializer
def serialize_rust_literal(value: RustLiteralVar):
    """Serialize a Rust-backed literal var (the cutover target of LiteralVar).

    Registered separately because ``RustLiteralVar`` is not a Python
    ``LiteralVar`` subclass, so ``get_serializer`` cannot reach
    ``serialize_literal`` via ``issubclass``.

    Args:
        value: The Rust literal var to serialize.

    Returns:
        The serialized literal value.
    """
    return value._var_value


def get_python_literal(value: LiteralVar | Any) -> Any | None:
    """Get the Python literal value.

    Args:
        value: The value to get the Python literal value of.

    Returns:
        The Python literal value.
    """
    if isinstance(value, LiteralVar):
        return value._var_value
    if isinstance(value, Var):
        return None
    return value


P = ParamSpec("P")
T = TypeVar("T")
U = TypeVar("U")


# NoReturn is used to match CustomVarOperationReturn with no type hint.
@overload
def var_operation(  # pyright: ignore [reportOverlappingOverload]
    func: Callable[P, CustomVarOperationReturn[NoReturn]],
) -> Callable[P, Var]: ...


@overload
def var_operation(
    func: Callable[P, CustomVarOperationReturn[None]],
) -> Callable[P, NoneVar]: ...


@overload
def var_operation(  # pyright: ignore [reportOverlappingOverload]
    func: Callable[P, CustomVarOperationReturn[bool]]
    | Callable[P, CustomVarOperationReturn[bool | None]],
) -> Callable[P, BooleanVar]: ...


NUMBER_T = TypeVar("NUMBER_T", int, float, int | float)


@overload
def var_operation(
    func: Callable[P, CustomVarOperationReturn[NUMBER_T]]
    | Callable[P, CustomVarOperationReturn[NUMBER_T | None]],
) -> Callable[P, NumberVar[NUMBER_T]]: ...


@overload
def var_operation(
    func: Callable[P, CustomVarOperationReturn[str]]
    | Callable[P, CustomVarOperationReturn[str | None]],
) -> Callable[P, StringVar]: ...


LIST_T = TypeVar("LIST_T", bound=Sequence)


@overload
def var_operation(
    func: Callable[P, CustomVarOperationReturn[LIST_T]]
    | Callable[P, CustomVarOperationReturn[LIST_T | None]],
) -> Callable[P, ArrayVar[LIST_T]]: ...


OBJECT_TYPE = TypeVar("OBJECT_TYPE", bound=Mapping)


@overload
def var_operation(
    func: Callable[P, CustomVarOperationReturn[OBJECT_TYPE]]
    | Callable[P, CustomVarOperationReturn[OBJECT_TYPE | None]],
) -> Callable[P, ObjectVar[OBJECT_TYPE]]: ...


@overload
def var_operation(
    func: Callable[P, CustomVarOperationReturn[T]]
    | Callable[P, CustomVarOperationReturn[T | None]],
) -> Callable[P, Var[T]]: ...


def var_operation(  # pyright: ignore [reportInconsistentOverload]
    func: Callable[P, CustomVarOperationReturn[T]],
) -> Callable[P, Var[T]]:
    """Decorator for creating a var operation.

    Example:
    ```python
    @var_operation
    def add(a: NumberVar, b: NumberVar):
        return custom_var_operation(f"{a} + {b}")
    ```

    Args:
        func: The function to decorate.

    Returns:
        The decorated function.
    """
    func_args = list(inspect.signature(func).parameters)

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Var[T]:
        args_vars = {
            func_args[i]: (LiteralVar.create(arg) if not isinstance(arg, Var) else arg)
            for i, arg in enumerate(args)
        }
        kwargs_vars = {
            key: LiteralVar.create(value) if not isinstance(value, Var) else value
            for key, value in kwargs.items()
        }

        return CustomVarOperation.create(
            name=func.__name__,
            args=tuple(list(args_vars.items()) + list(kwargs_vars.items())),
            return_var=func(*args_vars.values(), **kwargs_vars),  # pyright: ignore [reportCallIssue, reportReturnType]
        ).guess_type()

    return wrapper


def figure_out_type(value: Any) -> types.GenericType:
    """Figure out the type of the value.

    Args:
        value: The value to figure out the type of.

    Returns:
        The type of the value.
    """
    if isinstance(value, (list, set, tuple, Mapping, Var)):
        if isinstance(value, Var):
            return value._var_type
        if has_args(value_type := type(value)):
            return value_type
        if isinstance(value, list):
            if not value:
                return Sequence[NoReturn]
            return Sequence[unionize(*{figure_out_type(v) for v in value[:100]})]
        if isinstance(value, set):
            return set[unionize(*{figure_out_type(v) for v in value})]
        if isinstance(value, tuple):
            if not value:
                return tuple[NoReturn, ...]
            if len(value) <= 5:
                return tuple[tuple(figure_out_type(v) for v in value)]
            return tuple[unionize(*{figure_out_type(v) for v in value[:100]}), ...]
        if isinstance(value, Mapping):
            if not value:
                return Mapping[NoReturn, NoReturn]
            return Mapping[
                unionize(*{figure_out_type(k) for k in list(value.keys())[:100]}),
                unionize(*{figure_out_type(v) for v in list(value.values())[:100]}),
            ]
    return type(value)


GLOBAL_CACHE = {}


class cached_property:  # noqa: N801
    """A cached property that caches the result of the function."""

    def __init__(self, func: Callable):
        """Initialize the cached_property.

        Args:
            func: The function to cache.
        """
        self._func = func
        self._attrname = None

    def __set_name__(self, owner: Any, name: str):
        """Set the name of the cached property.

        Args:
            owner: The owner of the cached property.
            name: The name of the cached property.

        Raises:
            TypeError: If the cached property is assigned to two different names.
        """
        if self._attrname is None:
            self._attrname = name

            original_del = getattr(owner, "__del__", None)

            def delete_property(this: Any):
                """Delete the cached property.

                Args:
                    this: The object to delete the cached property from.
                """
                cached_field_name = "_reflex_cache_" + name
                try:
                    unique_id = object.__getattribute__(this, cached_field_name)
                except AttributeError:
                    if original_del is not None:
                        original_del(this)
                    return
                GLOBAL_CACHE.pop(unique_id, None)

                if original_del is not None:
                    original_del(this)

            owner.__del__ = delete_property

        elif name != self._attrname:
            msg = (
                "Cannot assign the same cached_property to two different names "
                f"({self._attrname!r} and {name!r})."
            )
            raise TypeError(msg)

    def __get__(self, instance: Any, owner: type | None = None):
        """Get the cached property.

        Args:
            instance: The instance to get the cached property from.
            owner: The owner of the cached property.

        Returns:
            The cached property.

        Raises:
            TypeError: If the class does not have __set_name__.
        """
        if self._attrname is None:
            msg = "Cannot use cached_property on a class without __set_name__."
            raise TypeError(msg)
        cached_field_name = "_reflex_cache_" + self._attrname
        try:
            unique_id = object.__getattribute__(instance, cached_field_name)
        except AttributeError:
            unique_id = uuid.uuid4().int
            object.__setattr__(instance, cached_field_name, unique_id)
        if unique_id not in GLOBAL_CACHE:
            GLOBAL_CACHE[unique_id] = self._func(instance)
        return GLOBAL_CACHE[unique_id]


cached_property_no_lock = cached_property


class VarProtocol(Protocol):
    """A protocol for Var."""

    __dataclass_fields__: ClassVar[dict[str, dataclasses.Field[Any]]]

    @property
    def _js_expr(self) -> str: ...

    @property
    def _var_type(self) -> types.GenericType: ...

    @property
    def _var_data(self) -> VarData: ...


class CachedVarOperation:
    """Base class for cached var operations to lower boilerplate code."""

    def __post_init__(self):
        """Post-initialize the CachedVarOperation."""
        object.__delattr__(self, "_js_expr")

    def __getattr__(self, name: str) -> Any:
        """Get an attribute of the var.

        Args:
            name: The name of the attribute.

        Returns:
            The attribute.
        """
        if name == "_js_expr":
            return self._cached_var_name

        parent_classes = inspect.getmro(type(self))

        next_class = parent_classes[parent_classes.index(CachedVarOperation) + 1]

        return next_class.__getattr__(self, name)

    def _get_all_var_data(self) -> VarData | None:
        """Get all VarData associated with the Var.

        Returns:
            The VarData of the components and all of its children.
        """
        return self._cached_get_all_var_data

    @cached_property_no_lock
    def _cached_get_all_var_data(self: VarProtocol) -> VarData | None:
        """Get the cached VarData.

        Returns:
            The cached VarData.
        """
        return VarData.merge(
            *(
                value._get_all_var_data() if isinstance(value, Var) else None
                for value in (
                    getattr(self, field.name) for field in dataclasses.fields(self)
                )
            ),
            self._var_data,
        )

    def __hash__(self: DataclassInstance) -> int:
        """Calculate the hash of the object.

        Returns:
            The hash of the object.
        """
        return hash((
            type(self).__name__,
            *[
                getattr(self, field.name)
                for field in dataclasses.fields(self)
                if field.name not in ["_js_expr", "_var_data", "_var_type"]
            ],
        ))


def and_operation(
    a: Var[VAR_TYPE] | Any, b: Var[OTHER_VAR_TYPE] | Any
) -> Var[VAR_TYPE | OTHER_VAR_TYPE]:
    """Perform a logical AND operation on two variables.

    Args:
        a: The first variable.
        b: The second variable.

    Returns:
        The result of the logical AND operation.
    """
    return _and_operation(a, b)


@var_operation
def _and_operation(a: Var, b: Var):
    """Perform a logical AND operation on two variables.

    Args:
        a: The first variable.
        b: The second variable.

    Returns:
        The result of the logical AND operation.
    """
    return var_operation_return(
        js_expression=f"({a} && {b})",
        var_type=unionize(a._var_type, b._var_type),
    )


def or_operation(
    a: Var[VAR_TYPE] | Any, b: Var[OTHER_VAR_TYPE] | Any
) -> Var[VAR_TYPE | OTHER_VAR_TYPE]:
    """Perform a logical OR operation on two variables.

    Args:
        a: The first variable.
        b: The second variable.

    Returns:
        The result of the logical OR operation.
    """
    return _or_operation(a, b)


@var_operation
def _or_operation(a: Var, b: Var):
    """Perform a logical OR operation on two variables.

    Args:
        a: The first variable.
        b: The second variable.

    Returns:
        The result of the logical OR operation.
    """
    return var_operation_return(
        js_expression=f"({a} || {b})",
        var_type=unionize(a._var_type, b._var_type),
    )


RETURN_TYPE = TypeVar("RETURN_TYPE")

DICT_KEY = TypeVar("DICT_KEY")
DICT_VAL = TypeVar("DICT_VAL")

LIST_INSIDE = TypeVar("LIST_INSIDE")


class FakeComputedVarBaseClass(property):
    """A fake base class for ComputedVar to avoid inheriting from property."""

    __pydantic_run_validation__ = False


def is_computed_var(obj: Any) -> TypeGuard[ComputedVar]:
    """Check if the object is a ComputedVar.

    Args:
        obj: The object to check.

    Returns:
        Whether the object is a ComputedVar.
    """
    return isinstance(obj, FakeComputedVarBaseClass)


@dataclasses.dataclass(
    eq=False,
    frozen=True,
    slots=True,
)
class ComputedVar(Var[RETURN_TYPE]):
    """A field with computed getters."""

    # Whether to track dependencies and cache computed values
    _cache: bool = dataclasses.field(default=False)

    # Whether the computed var is a backend var
    _backend: bool = dataclasses.field(default=False)

    # The initial value of the computed var
    _initial_value: RETURN_TYPE | types.Unset = dataclasses.field(default=types.Unset())

    # Explicit var dependencies to track
    _static_deps: dict[str | None, set[str]] = dataclasses.field(default_factory=dict)

    # Whether var dependencies should be auto-determined
    _auto_deps: bool = dataclasses.field(default=True)

    # Interval at which the computed var should be updated
    _update_interval: datetime.timedelta | None = dataclasses.field(default=None)

    _fget: Callable[[BaseState], RETURN_TYPE] = dataclasses.field(
        default_factory=lambda: lambda _: None
    )  # pyright: ignore [reportAssignmentType]

    _name: str = dataclasses.field(default="")

    def __init__(
        self,
        fget: Callable[[BASE_STATE], RETURN_TYPE],
        initial_value: RETURN_TYPE | types.Unset = types.Unset(),
        cache: bool = True,
        deps: list[str | Var] | None = None,
        auto_deps: bool = True,
        interval: int | datetime.timedelta | None = None,
        backend: bool | None = None,
        **kwargs,
    ):
        """Initialize a ComputedVar.

        Args:
            fget: The getter function.
            initial_value: The initial value of the computed var.
            cache: Whether to cache the computed value.
            deps: Explicit var dependencies to track.
            auto_deps: Whether var dependencies should be auto-determined.
            interval: Interval at which the computed var should be updated.
            backend: Whether the computed var is a backend var.
            **kwargs: additional attributes to set on the instance

        Raises:
            TypeError: If the computed var dependencies are not Var instances or var names.
            UntypedComputedVarError: If the computed var is untyped.
        """
        hint = kwargs.pop("return_type", None) or get_type_hints(fget).get(
            "return", Any
        )

        if hint is Any:
            raise UntypedComputedVarError(var_name=fget.__name__)
        is_using_fget_name = "_js_expr" not in kwargs
        js_expr = kwargs.pop("_js_expr", fget.__name__ + FIELD_MARKER)
        kwargs.setdefault("_var_type", hint)

        Var.__init__(
            self,
            _js_expr=js_expr,
            _var_type=kwargs.pop("_var_type"),
            _var_data=kwargs.pop(
                "_var_data",
                VarData(field_name=fget.__name__) if is_using_fget_name else None,
            ),
        )

        if kwargs:
            msg = f"Unexpected keyword arguments: {tuple(kwargs)}"
            raise TypeError(msg)

        if backend is None:
            backend = fget.__name__.startswith("_")

        object.__setattr__(self, "_backend", backend)
        object.__setattr__(self, "_initial_value", initial_value)
        object.__setattr__(self, "_cache", cache)
        object.__setattr__(self, "_name", fget.__name__)

        if isinstance(interval, int):
            interval = datetime.timedelta(seconds=interval)

        object.__setattr__(self, "_update_interval", interval)

        object.__setattr__(
            self,
            "_static_deps",
            self._calculate_static_deps(deps),
        )
        object.__setattr__(self, "_auto_deps", auto_deps)

        object.__setattr__(self, "_fget", fget)

    def _calculate_static_deps(
        self,
        deps: list[str | Var] | dict[str | None, set[str]] | None = None,
    ) -> dict[str | None, set[str]]:
        """Calculate the static dependencies of the computed var from user input or existing dependencies.

        Args:
            deps: The user input dependencies or existing dependencies.

        Returns:
            The static dependencies.
        """
        if isinstance(deps, dict):
            # Assume a dict is coming from _replace, so no special processing.
            return deps
        static_deps = {}
        if deps is not None:
            for dep in deps:
                static_deps = self._add_static_dep(dep, static_deps)
        return static_deps

    def _add_static_dep(
        self, dep: str | Var, deps: dict[str | None, set[str]] | None = None
    ) -> dict[str | None, set[str]]:
        """Add a static dependency to the computed var or existing dependency set.

        Args:
            dep: The dependency to add.
            deps: The existing dependency set.

        Returns:
            The updated dependency set.

        Raises:
            TypeError: If the computed var dependencies are not Var instances or var names.
        """
        if deps is None:
            deps = self._static_deps
        if isinstance(dep, Var):
            state_name = (
                all_var_data.state
                if (all_var_data := dep._get_all_var_data()) and all_var_data.state
                else None
            )
            if all_var_data is not None:
                var_name = all_var_data.field_name
            else:
                var_name = dep._js_expr
            deps.setdefault(state_name, set()).add(var_name)
        elif isinstance(dep, str) and dep != "":
            deps.setdefault(None, set()).add(dep)
        else:
            msg = "ComputedVar dependencies must be Var instances or var names (non-empty strings)."
            raise TypeError(msg)
        return deps

    @override
    def _replace(
        self,
        merge_var_data: VarData | None = None,
        **kwargs: Any,
    ) -> Self:
        """Replace the attributes of the ComputedVar.

        Args:
            merge_var_data: VarData to merge into the existing VarData.
            **kwargs: Var fields to update.

        Returns:
            The new ComputedVar instance.

        Raises:
            TypeError: If kwargs contains keys that are not allowed.
        """
        if "deps" in kwargs:
            kwargs["deps"] = self._calculate_static_deps(kwargs["deps"])
        field_values = {
            "fget": kwargs.pop("fget", self._fget),
            "initial_value": kwargs.pop("initial_value", self._initial_value),
            "cache": kwargs.pop("cache", self._cache),
            "deps": kwargs.pop("deps", copy.copy(self._static_deps)),
            "auto_deps": kwargs.pop("auto_deps", self._auto_deps),
            "interval": kwargs.pop("interval", self._update_interval),
            "backend": kwargs.pop("backend", self._backend),
            "_js_expr": kwargs.pop("_js_expr", self._js_expr),
            "_var_type": kwargs.pop("_var_type", self._var_type),
            "_var_data": kwargs.pop(
                "_var_data", VarData.merge(self._var_data, merge_var_data)
            ),
            "return_type": kwargs.pop("return_type", self._var_type),
        }

        if kwargs:
            unexpected_kwargs = ", ".join(kwargs.keys())
            msg = f"Unexpected keyword arguments: {unexpected_kwargs}"
            raise TypeError(msg)

        return type(self)(**field_values)

    @property
    def _cache_attr(self) -> str:
        """Get the attribute used to cache the value on the instance.

        Returns:
            An attribute name.
        """
        return f"__cached_{self._js_expr}"

    @property
    def _last_updated_attr(self) -> str:
        """Get the attribute used to store the last updated timestamp.

        Returns:
            An attribute name.
        """
        return f"__last_updated_{self._js_expr}"

    def needs_update(self, instance: BaseState) -> bool:
        """Check if the computed var needs to be updated.

        Args:
            instance: The state instance that the computed var is attached to.

        Returns:
            True if the computed var needs to be updated, False otherwise.
        """
        if self._update_interval is None:
            return False
        last_updated = getattr(instance, self._last_updated_attr, None)
        if last_updated is None:
            return True
        return datetime.datetime.now() - last_updated > self._update_interval

    @overload
    def __get__(
        self: ComputedVar[bool],
        instance: None,
        owner: type,
    ) -> BooleanVar: ...

    @overload
    def __get__(
        self: ComputedVar[int] | ComputedVar[float],
        instance: None,
        owner: type,
    ) -> NumberVar: ...

    @overload
    def __get__(
        self: ComputedVar[str],
        instance: None,
        owner: type,
    ) -> StringVar: ...

    @overload
    def __get__(
        self: ComputedVar[MAPPING_TYPE],
        instance: None,
        owner: type,
    ) -> ObjectVar[MAPPING_TYPE]: ...

    @overload
    def __get__(
        self: ComputedVar[list[LIST_INSIDE]],
        instance: None,
        owner: type,
    ) -> ArrayVar[list[LIST_INSIDE]]: ...

    @overload
    def __get__(
        self: ComputedVar[tuple[LIST_INSIDE, ...]],
        instance: None,
        owner: type,
    ) -> ArrayVar[tuple[LIST_INSIDE, ...]]: ...

    @overload
    def __get__(
        self: ComputedVar[SQLA_TYPE],
        instance: None,
        owner: type,
    ) -> ObjectVar[SQLA_TYPE]: ...

    if TYPE_CHECKING:

        @overload
        def __get__(
            self: ComputedVar[DATACLASS_TYPE], instance: None, owner: Any
        ) -> ObjectVar[DATACLASS_TYPE]: ...

    @overload
    def __get__(self, instance: None, owner: type) -> ComputedVar[RETURN_TYPE]: ...

    @overload
    def __get__(self, instance: BaseState, owner: type) -> RETURN_TYPE: ...

    def __get__(self, instance: BaseState | None, owner: type):
        """Get the ComputedVar value.

        If the value is already cached on the instance, return the cached value.

        Args:
            instance: the instance of the class accessing this computed var.
            owner: the class that this descriptor is attached to.

        Returns:
            The value of the var for the given instance.
        """
        if instance is None:
            state_where_defined = owner
            while self._name in state_where_defined.inherited_vars:
                state_where_defined = state_where_defined.get_parent_state()

            field_name = (
                format_state_name(state_where_defined.get_full_name())
                + "."
                + self._js_expr
            )

            return dispatch(
                field_name,
                var_data=VarData.from_state(state_where_defined, self._name),
                result_var_type=self._var_type,
            )

        if not self._cache:
            value = self.fget(instance)
        else:
            # handle caching
            if not hasattr(instance, self._cache_attr) or self.needs_update(instance):
                # Set cache attr on state instance.
                setattr(instance, self._cache_attr, self.fget(instance))
                # Ensure the computed var gets serialized to redis.
                instance._was_touched = True
                # Set the last updated timestamp on the state instance.
                setattr(instance, self._last_updated_attr, datetime.datetime.now())
            value = getattr(instance, self._cache_attr)

        self._check_deprecated_return_type(instance, value)

        return value

    def _check_deprecated_return_type(self, instance: BaseState, value: Any) -> None:
        if not _isinstance(value, self._var_type, nested=1, treat_var_as_type=False):
            console.error(
                f"Computed var '{type(instance).__name__}.{self._name}' must return"
                f" a value of type '{escape(str(self._var_type))}', got '{value!s}' of type {type(value)}."
            )

    def _deps(
        self,
        objclass: type[BaseState],
        obj: FunctionType | CodeType | None = None,
    ) -> dict[str, set[str]]:
        """Determine var dependencies of this ComputedVar.

        Save references to attributes accessed on "self" or other fetched states.

        Recursively called when the function makes a method call on "self" or
        define comprehensions or nested functions that may reference "self".

        Args:
            objclass: the class obj this ComputedVar is attached to.
            obj: the object to disassemble (defaults to the fget function).

        Returns:
            A dictionary mapping state names to the set of variable names
            accessed by the given obj.
        """
        from .dep_tracking import DependencyTracker

        d = {}
        if self._static_deps:
            d.update(self._static_deps)
            # None is a placeholder for the current state class.
            if None in d:
                d[objclass.get_full_name()] = d.pop(None)

        if not self._auto_deps:
            return d

        if obj is None:
            fget = self._fget
            if fget is not None:
                obj = cast(FunctionType, fget)
            else:
                return d

        try:
            return DependencyTracker(
                func=obj, state_cls=objclass, dependencies=d
            ).dependencies
        except Exception as e:
            console.warn(
                "Failed to automatically determine dependencies for computed var "
                f"{objclass.__name__}.{self._name}: {e}. "
                "Set auto_deps=False and provide accurate deps=['var1', 'var2'] to suppress this warning."
            )
            return d

    def mark_dirty(self, instance: BaseState) -> None:
        """Mark this ComputedVar as dirty.

        Args:
            instance: the state instance that needs to recompute the value.
        """
        with contextlib.suppress(AttributeError):
            delattr(instance, self._cache_attr)

    def add_dependency(self, objclass: type[BaseState], dep: Var):
        """Explicitly add a dependency to the ComputedVar.

        After adding the dependency, when the `dep` changes, this computed var
        will be marked dirty.

        Args:
            objclass: The class obj this ComputedVar is attached to.
            dep: The dependency to add.

        Raises:
            VarDependencyError: If the dependency is not a Var instance with a
                state and field name
        """
        if all_var_data := dep._get_all_var_data():
            state_name = all_var_data.state
            if state_name:
                var_name = all_var_data.field_name
                if var_name:
                    self._static_deps.setdefault(state_name, set()).add(var_name)
                    target_state_class = objclass.get_root_state().get_class_substate(
                        state_name
                    )
                    target_state_class._var_dependencies.setdefault(
                        var_name, set()
                    ).add((
                        objclass.get_full_name(),
                        self._name,
                    ))
                    target_state_class._potentially_dirty_states.add(
                        objclass.get_full_name()
                    )
                    return
        msg = (
            "ComputedVar dependencies must be Var instances with a state and "
            f"field name, got {dep!r}."
        )
        raise VarDependencyError(msg)

    def _determine_var_type(self) -> type:
        """Get the type of the var.

        Returns:
            The type of the var.
        """
        hints = get_type_hints(self._fget)
        if "return" in hints:
            return hints["return"]
        return Any  # pyright: ignore [reportReturnType]

    @property
    def __class__(self) -> type:
        """Get the class of the var.

        Returns:
            The class of the var.
        """
        return FakeComputedVarBaseClass

    @property
    def fget(self) -> Callable[[BaseState], RETURN_TYPE]:
        """Get the getter function.

        Returns:
            The getter function.
        """
        return self._fget


class DynamicRouteVar(ComputedVar[str | list[str]]):
    """A ComputedVar that represents a dynamic route."""


async def _default_async_computed_var(_self: BaseState) -> Any:  # noqa: RUF029
    return None


@dataclasses.dataclass(
    eq=False,
    frozen=True,
    init=False,
    slots=True,
)
class AsyncComputedVar(ComputedVar[RETURN_TYPE]):
    """A computed var that wraps a coroutinefunction."""

    _fget: Callable[[BaseState], Coroutine[None, None, RETURN_TYPE]] = (
        dataclasses.field(default=_default_async_computed_var)
    )

    @overload
    def __get__(
        self: AsyncComputedVar[bool],
        instance: None,
        owner: type,
    ) -> BooleanVar: ...

    @overload
    def __get__(
        self: AsyncComputedVar[int] | ComputedVar[float],
        instance: None,
        owner: type,
    ) -> NumberVar: ...

    @overload
    def __get__(
        self: AsyncComputedVar[str],
        instance: None,
        owner: type,
    ) -> StringVar: ...

    @overload
    def __get__(
        self: AsyncComputedVar[MAPPING_TYPE],
        instance: None,
        owner: type,
    ) -> ObjectVar[MAPPING_TYPE]: ...

    @overload
    def __get__(
        self: AsyncComputedVar[list[LIST_INSIDE]],
        instance: None,
        owner: type,
    ) -> ArrayVar[list[LIST_INSIDE]]: ...

    @overload
    def __get__(
        self: AsyncComputedVar[tuple[LIST_INSIDE, ...]],
        instance: None,
        owner: type,
    ) -> ArrayVar[tuple[LIST_INSIDE, ...]]: ...

    @overload
    def __get__(
        self: AsyncComputedVar[SQLA_TYPE],
        instance: None,
        owner: type,
    ) -> ObjectVar[SQLA_TYPE]: ...

    if TYPE_CHECKING:

        @overload
        def __get__(
            self: AsyncComputedVar[DATACLASS_TYPE], instance: None, owner: Any
        ) -> ObjectVar[DATACLASS_TYPE]: ...

    @overload
    def __get__(self, instance: None, owner: type) -> AsyncComputedVar[RETURN_TYPE]: ...

    @overload
    def __get__(
        self, instance: BaseState, owner: type
    ) -> Coroutine[None, None, RETURN_TYPE]: ...

    def __get__(
        self, instance: BaseState | None, owner
    ) -> Var | Coroutine[None, None, RETURN_TYPE]:
        """Get the ComputedVar value.

        If the value is already cached on the instance, return the cached value.

        Args:
            instance: the instance of the class accessing this computed var.
            owner: the class that this descriptor is attached to.

        Returns:
            The value of the var for the given instance.
        """
        if instance is None:
            return super(AsyncComputedVar, self).__get__(instance, owner)

        if not self._cache:

            async def _awaitable_result(instance: BaseState = instance) -> RETURN_TYPE:
                value = await self.fget(instance)
                self._check_deprecated_return_type(instance, value)
                return value

            return _awaitable_result()

        # handle caching
        async def _awaitable_result(instance: BaseState = instance) -> RETURN_TYPE:
            if not hasattr(instance, self._cache_attr) or self.needs_update(instance):
                # Set cache attr on state instance.
                setattr(instance, self._cache_attr, await self.fget(instance))
                # Ensure the computed var gets serialized to redis.
                instance._was_touched = True
                # Set the last updated timestamp on the state instance.
                setattr(instance, self._last_updated_attr, datetime.datetime.now())
            value = getattr(instance, self._cache_attr)
            self._check_deprecated_return_type(instance, value)
            return value

        return _awaitable_result()

    @property
    def fget(self) -> Callable[[BaseState], Coroutine[None, None, RETURN_TYPE]]:
        """Get the getter function.

        Returns:
            The getter function.
        """
        return self._fget


if TYPE_CHECKING:
    BASE_STATE = TypeVar("BASE_STATE", bound=BaseState)


class _ComputedVarDecorator(Protocol):
    """A protocol for the ComputedVar decorator."""

    @overload
    def __call__(
        self,
        fget: Callable[[BASE_STATE], Coroutine[Any, Any, RETURN_TYPE]],
    ) -> AsyncComputedVar[RETURN_TYPE]: ...

    @overload
    def __call__(
        self,
        fget: Callable[[BASE_STATE], RETURN_TYPE],
    ) -> ComputedVar[RETURN_TYPE]: ...

    def __call__(
        self,
        fget: Callable[[BASE_STATE], Any],
    ) -> ComputedVar[Any]: ...


@overload
def computed_var(
    fget: None = None,
    initial_value: Any | types.Unset = types.Unset(),
    cache: bool = True,
    deps: list[str | Var] | None = None,
    auto_deps: bool = True,
    interval: datetime.timedelta | int | None = None,
    backend: bool | None = None,
    **kwargs,
) -> _ComputedVarDecorator: ...


@overload
def computed_var(
    fget: Callable[[BASE_STATE], Coroutine[Any, Any, RETURN_TYPE]],
    initial_value: RETURN_TYPE | types.Unset = types.Unset(),
    cache: bool = True,
    deps: list[str | Var] | None = None,
    auto_deps: bool = True,
    interval: datetime.timedelta | int | None = None,
    backend: bool | None = None,
    **kwargs,
) -> AsyncComputedVar[RETURN_TYPE]: ...


@overload
def computed_var(
    fget: Callable[[BASE_STATE], RETURN_TYPE],
    initial_value: RETURN_TYPE | types.Unset = types.Unset(),
    cache: bool = True,
    deps: list[str | Var] | None = None,
    auto_deps: bool = True,
    interval: datetime.timedelta | int | None = None,
    backend: bool | None = None,
    **kwargs,
) -> ComputedVar[RETURN_TYPE]: ...


def computed_var(
    fget: Callable[[BASE_STATE], Any] | None = None,
    initial_value: Any | types.Unset = types.Unset(),
    cache: bool = True,
    deps: list[str | Var] | None = None,
    auto_deps: bool = True,
    interval: datetime.timedelta | int | None = None,
    backend: bool | None = None,
    **kwargs,
) -> ComputedVar | Callable[[Callable[[BASE_STATE], Any]], ComputedVar]:
    """A ComputedVar decorator with or without kwargs.

    Args:
        fget: The getter function.
        initial_value: The initial value of the computed var.
        cache: Whether to cache the computed value.
        deps: Explicit var dependencies to track.
        auto_deps: Whether var dependencies should be auto-determined.
        interval: Interval at which the computed var should be updated.
        backend: Whether the computed var is a backend var.
        **kwargs: additional attributes to set on the instance

    Returns:
        A ComputedVar instance.

    Raises:
        ValueError: If caching is disabled and an update interval is set.
        VarDependencyError: If user supplies dependencies without caching.
        ComputedVarSignatureError: If the getter function has more than one argument.
    """
    if cache is False and interval is not None:
        msg = "Cannot set update interval without caching."
        raise ValueError(msg)

    if cache is False and (deps is not None or auto_deps is False):
        msg = "Cannot track dependencies without caching."
        raise VarDependencyError(msg)

    if fget is not None:
        sign = inspect.signature(fget)
        if len(sign.parameters) != 1:
            raise ComputedVarSignatureError(fget.__name__, signature=str(sign))

        if inspect.iscoroutinefunction(fget):
            computed_var_cls = AsyncComputedVar
        else:
            computed_var_cls = ComputedVar
        return computed_var_cls(
            fget,
            initial_value=initial_value,
            cache=cache,
            deps=deps,
            auto_deps=auto_deps,
            interval=interval,
            backend=backend,
            **kwargs,
        )

    def wrapper(fget: Callable[[BASE_STATE], Any]) -> ComputedVar:
        if inspect.iscoroutinefunction(fget):
            computed_var_cls = AsyncComputedVar
        else:
            computed_var_cls = ComputedVar
        return computed_var_cls(
            fget,
            initial_value=initial_value,
            cache=cache,
            deps=deps,
            auto_deps=auto_deps,
            interval=interval,
            backend=backend,
            **kwargs,
        )

    return wrapper


RETURN = TypeVar("RETURN")


class CustomVarOperationReturn(Var[RETURN]):
    """Base class for custom var operations."""

    @classmethod
    def create(
        cls,
        js_expression: str,
        _var_type: type[RETURN] | None = None,
        _var_data: VarData | None = None,
    ) -> CustomVarOperationReturn[RETURN]:
        """Create a CustomVarOperation.

        Args:
            js_expression: The JavaScript expression to evaluate.
            _var_type: The type of the var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The CustomVarOperation.
        """
        return CustomVarOperationReturn(
            _js_expr=js_expression,
            _var_type=_var_type or Any,
            _var_data=_var_data,
        )


def var_operation_return(
    js_expression: str,
    var_type: type[RETURN] | GenericType | None = None,
    var_data: VarData | None = None,
) -> CustomVarOperationReturn[RETURN]:
    """Shortcut for creating a CustomVarOperationReturn.

    Args:
        js_expression: The JavaScript expression to evaluate.
        var_type: The type of the var.
        var_data: Additional hooks and imports associated with the Var.

    Returns:
        The CustomVarOperationReturn.
    """
    return CustomVarOperationReturn.create(
        js_expression,
        var_type,
        var_data,
    )


@dataclasses.dataclass(
    eq=False,
    frozen=True,
    slots=True,
)
class CustomVarOperation(CachedVarOperation, Var[T]):
    """Base class for custom var operations."""

    _name: str = dataclasses.field(default="")

    _args: tuple[tuple[str, Var], ...] = dataclasses.field(default_factory=tuple)

    _return: CustomVarOperationReturn[T] = dataclasses.field(
        default_factory=lambda: CustomVarOperationReturn.create("")
    )

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """Get the cached var name.

        Returns:
            The cached var name.
        """
        return str(self._return)

    @cached_property_no_lock
    def _cached_get_all_var_data(self) -> VarData | None:
        """Get the cached VarData.

        Returns:
            The cached VarData.
        """
        return VarData.merge(
            *(arg[1]._get_all_var_data() for arg in self._args),
            self._return._get_all_var_data(),
            self._var_data,
        )

    @classmethod
    def create(
        cls,
        name: str,
        args: tuple[tuple[str, Var], ...],
        return_var: CustomVarOperationReturn[T],
        _var_data: VarData | None = None,
    ) -> CustomVarOperation[T]:
        """Create a CustomVarOperation.

        Args:
            name: The name of the operation.
            args: The arguments to the operation.
            return_var: The return var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The CustomVarOperation (a RustVar).
        """
        # A var operation's rendered name is the (already marker-decoded) return
        # expression; its var_data is the merge of each arg, the return, and any
        # extra. Build the Rust var directly — the operation result is a RustVar.
        var_data = VarData.merge(
            *(arg[1]._get_all_var_data() for arg in args),
            return_var._get_all_var_data(),
            _var_data,
        )
        return Var(
            _js_expr=str(return_var),
            _var_type=return_var._var_type,
            _var_data=var_data,
        ).guess_type()


class NoneVar(Var[None], python_types=type(None)):
    """A var representing None."""


@dataclasses.dataclass(
    eq=False,
    frozen=True,
    slots=True,
)
class LiteralNoneVar(LiteralVar[None], NoneVar):
    """A var representing None."""

    _var_value: None = None

    def json(self) -> str:
        """Serialize the var to a JSON string.

        Returns:
            The JSON string.
        """
        return "null"

    @classmethod
    def _get_all_var_data_without_creating_var(cls, value: None) -> VarData | None:
        return None

    @classmethod
    def create(
        cls,
        value: None = None,
        _var_data: VarData | None = None,
    ) -> LiteralNoneVar:
        """Create a var from a value.

        Args:
            value: The value of the var. Must be None. Existed for compatibility with LiteralVar.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The var.
        """
        return LiteralNoneVar(
            _js_expr="null",
            _var_type=None,
            _var_data=_var_data,
        )


def get_to_operation(var_subclass: type[Var]) -> type[ToOperation]:
    """Get the ToOperation class for a given Var subclass.

    Args:
        var_subclass: The Var subclass.

    Returns:
        The ToOperation class.

    Raises:
        ValueError: If the ToOperation class cannot be found.
    """
    possible_classes = [
        saved_var_subclass.to_var_subclass
        for saved_var_subclass in _var_subclasses
        if saved_var_subclass.var_subclass is var_subclass
    ]
    if not possible_classes:
        msg = f"Could not find ToOperation for {var_subclass}."
        raise ValueError(msg)
    return possible_classes[0]


@dataclasses.dataclass(
    eq=False,
    frozen=True,
    slots=True,
)
class StateOperation(CachedVarOperation, Var):
    """A var operation that accesses a field on an object."""

    _state_name: str = dataclasses.field(default="")
    _field: Var = dataclasses.field(default_factory=lambda: LiteralNoneVar.create())

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """Get the cached var name.

        Returns:
            The cached var name.
        """
        return f"{self._state_name!s}.{self._field!s}"

    def __getattr__(self, name: str) -> Any:
        """Get an attribute of the var.

        Args:
            name: The name of the attribute.

        Returns:
            The attribute.
        """
        if name == "_js_expr":
            return self._cached_var_name

        return getattr(self._field, name)

    @classmethod
    def create(
        cls,
        state_name: str,
        field: Var,
        _var_data: VarData | None = None,
    ) -> StateOperation:
        """Create a DotOperation.

        Args:
            state_name: The name of the state.
            field: The field of the state.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The DotOperation.
        """
        return StateOperation(
            _js_expr="",
            _var_type=field._var_type,
            _var_data=_var_data,
            _state_name=state_name,
            _field=field,
        )


def get_uuid_string_var() -> Var:
    """Return a Var that generates a single memoized UUID via .web/utils/state.js.

    useMemo with an empty dependency array ensures that the generated UUID is
    consistent across re-renders of the component.

    Returns:
        A Var that generates a UUID at runtime.
    """
    from reflex_base.utils.imports import ImportVar
    from reflex_base.vars import Var

    unique_uuid_var = get_unique_variable_name()
    unique_uuid_var_data = VarData(
        imports={
            f"$/{constants.Dirs.STATE_PATH}": ImportVar(tag="generateUUID"),
            "react": "useMemo",
        },
        hooks={f"const {unique_uuid_var} = useMemo(generateUUID, [])": None},
    )

    return Var(
        _js_expr=unique_uuid_var,
        _var_type=str,
        _var_data=unique_uuid_var_data,
    )


# Set of unique variable names.
USED_VARIABLES = set()


@once
def _rng():
    import random

    return random.Random(42)


def get_unique_variable_name() -> str:
    """Get a unique variable name.

    Returns:
        The unique variable name.
    """
    name = "".join([_rng().choice(string.ascii_lowercase) for _ in range(8)])
    if name not in USED_VARIABLES:
        USED_VARIABLES.add(name)
        return name
    return get_unique_variable_name()


# Compile regex for finding reflex var tags.
_decode_var_pattern_re = (
    rf"{constants.REFLEX_VAR_OPENING_TAG}(.*?){constants.REFLEX_VAR_CLOSING_TAG}"
)
_decode_var_pattern = re.compile(_decode_var_pattern_re, flags=re.DOTALL)

# Defined global immutable vars.
_global_vars: dict[int, Var] = {}


dispatchers: dict[GenericType, Callable[[Var], Var]] = {}


def transform(fn: Callable[[Var], Var]) -> Callable[[Var], Var]:
    """Register a function to transform a Var.

    Args:
        fn: The function to register.

    Returns:
        The decorator.

    Raises:
        TypeError: If the return type of the function is not a Var.
        TypeError: If the Var return type does not have a generic type.
        ValueError: If a function for the generic type is already registered.
    """
    types = get_type_hints(fn)
    return_type = types["return"]

    origin = get_origin(return_type)

    if origin is not Var:
        msg = f"Expected return type of {fn.__name__} to be a Var, got {origin}."
        raise TypeError(msg)

    generic_args = get_args(return_type)

    if not generic_args:
        msg = f"Expected Var return type of {fn.__name__} to have a generic type."
        raise TypeError(msg)

    generic_type = get_origin(generic_args[0]) or generic_args[0]

    if generic_type in dispatchers:
        msg = f"Function for {generic_type} already registered."
        raise ValueError(msg)

    dispatchers[generic_type] = fn

    return fn


def dispatch(
    field_name: str,
    var_data: VarData,
    result_var_type: GenericType,
) -> Var:
    """Dispatch a Var to the appropriate transformation function.

    Args:
        field_name: The name of the field.
        var_data: The VarData associated with the Var.
        result_var_type: The type of the Var.

    Returns:
        The transformed Var.

    Raises:
        TypeError: If the return type of the function is not a Var.
        TypeError: If the Var return type does not have a generic type.
        TypeError: If the first argument of the function is not a Var.
        TypeError: If the first argument of the function does not have a generic type
    """
    result_origin_var_type = get_origin(result_var_type) or result_var_type

    if result_origin_var_type in dispatchers:
        fn = dispatchers[result_origin_var_type]
        fn_types = get_type_hints(fn)
        fn_first_arg_type = fn_types.get(
            next(iter(inspect.signature(fn).parameters.values())).name, Any
        )

        fn_return = fn_types.get("return", Any)

        fn_return_origin = get_origin(fn_return) or fn_return

        if fn_return_origin is not Var:
            msg = f"Expected return type of {fn.__name__} to be a Var, got {fn_return}."
            raise TypeError(msg)

        fn_return_generic_args = get_args(fn_return)

        if not fn_return_generic_args:
            msg = f"Expected generic type of {fn_return} to be a type."
            raise TypeError(msg)

        arg_origin = get_origin(fn_first_arg_type) or fn_first_arg_type

        if arg_origin is not Var:
            msg = f"Expected first argument of {fn.__name__} to be a Var, got {fn_first_arg_type}."
            raise TypeError(msg)

        arg_generic_args = get_args(fn_first_arg_type)

        if not arg_generic_args:
            msg = f"Expected generic type of {fn_first_arg_type} to be a type."
            raise TypeError(msg)

        fn_return_type = fn_return_generic_args[0]

        var = Var(
            field_name,
            _var_data=var_data,
            _var_type=fn_return_type,
        ).guess_type()

        return fn(var)

    return Var(
        field_name,
        _var_data=var_data,
        _var_type=result_var_type,
    ).guess_type()


if TYPE_CHECKING:
    from _typeshed import DataclassInstance
    from sqlalchemy.orm import DeclarativeBase

    SQLA_TYPE = TypeVar("SQLA_TYPE", bound=DeclarativeBase | None)
    DATACLASS_TYPE = TypeVar("DATACLASS_TYPE", bound=DataclassInstance | None)
    MAPPING_TYPE = TypeVar("MAPPING_TYPE", bound=Mapping | None)
    V = TypeVar("V")


FIELD_TYPE = TypeVar("FIELD_TYPE")


class Field(Generic[FIELD_TYPE]):
    """A field for a state."""

    if TYPE_CHECKING:
        type_: GenericType
        default: FIELD_TYPE | _MISSING_TYPE
        default_factory: Callable[[], FIELD_TYPE] | None

    def __init__(
        self,
        default: FIELD_TYPE | _MISSING_TYPE = MISSING,
        default_factory: Callable[[], FIELD_TYPE] | None = None,
        is_var: bool = True,
        annotated_type: GenericType  # pyright: ignore [reportRedeclaration]
        | _MISSING_TYPE = MISSING,
    ) -> None:
        """Initialize the field.

        Args:
            default: The default value for the field.
            default_factory: The default factory for the field.
            is_var: Whether the field is a Var.
            annotated_type: The annotated type for the field.
        """
        self.default = default
        self.default_factory = default_factory
        self.is_var = is_var
        if annotated_type is not MISSING:
            type_origin = get_origin(annotated_type) or annotated_type
            if type_origin is Field and (
                args := getattr(annotated_type, "__args__", None)
            ):
                annotated_type: GenericType = args[0]
                type_origin = get_origin(annotated_type) or annotated_type

            if self.default is MISSING and self.default_factory is None:
                default_value = types.get_default_value_for_type(annotated_type)
                if default_value is None and not types.is_optional(annotated_type):
                    annotated_type = annotated_type | None
                if types.is_immutable(default_value):
                    self.default = default_value
                else:
                    self.default_factory = functools.partial(
                        copy.deepcopy, default_value
                    )
            self.outer_type_ = self.annotated_type = annotated_type

            if type_origin is Annotated:
                type_origin = annotated_type.__origin__  # pyright: ignore [reportAttributeAccessIssue]

            self.type_ = self.type_origin = type_origin
        else:
            self.outer_type_ = self.annotated_type = self.type_ = self.type_origin = Any

    def default_value(self) -> FIELD_TYPE:
        """Get the default value for the field.

        Returns:
            The default value for the field.

        Raises:
            ValueError: If no default value or factory is provided.
        """
        if self.default is not MISSING:
            return self.default
        if self.default_factory is not None:
            return self.default_factory()
        msg = "No default value or factory provided."
        raise ValueError(msg)

    def __repr__(self) -> str:
        """Represent the field in a readable format.

        Returns:
            The string representation of the field.
        """
        annotated_type_str = (
            f", annotated_type={self.annotated_type!r}"
            if self.annotated_type is not MISSING
            else ""
        )
        if self.default is not MISSING:
            return f"Field(default={self.default!r}, is_var={self.is_var}{annotated_type_str})"
        return f"Field(default_factory={self.default_factory!r}, is_var={self.is_var}{annotated_type_str})"

    if TYPE_CHECKING:

        def __set__(self, instance: Any, value: FIELD_TYPE):
            """Set the Var.

            Args:
                instance: The instance of the class setting the Var.
                value: The value to set the Var to.

            # noqa: DAR101 self
            """

    @overload
    def __get__(self: Field[None], instance: None, owner: Any) -> NoneVar: ...

    @overload
    def __get__(
        self: Field[bool] | Field[bool | None], instance: None, owner: Any
    ) -> BooleanVar: ...

    @overload
    def __get__(
        self: Field[int] | Field[int | None],
        instance: None,
        owner: Any,
    ) -> NumberVar[int]: ...

    @overload
    def __get__(
        self: Field[float]
        | Field[int | float]
        | Field[float | None]
        | Field[int | float | None],
        instance: None,
        owner: Any,
    ) -> NumberVar: ...

    @overload
    def __get__(
        self: Field[str] | Field[str | None], instance: None, owner: Any
    ) -> StringVar: ...

    @overload
    def __get__(
        self: Field[list[V]]
        | Field[set[V]]
        | Field[list[V] | None]
        | Field[set[V] | None],
        instance: None,
        owner: Any,
    ) -> ArrayVar[Sequence[V]]: ...

    @overload
    def __get__(
        self: Field[SEQUENCE_TYPE] | Field[SEQUENCE_TYPE | None],
        instance: None,
        owner: Any,
    ) -> ArrayVar[SEQUENCE_TYPE]: ...

    @overload
    def __get__(
        self: Field[MAPPING_TYPE] | Field[MAPPING_TYPE | None],
        instance: None,
        owner: Any,
    ) -> ObjectVar[MAPPING_TYPE]: ...

    @overload
    def __get__(
        self: Field[SQLA_TYPE] | Field[SQLA_TYPE | None], instance: None, owner: Any
    ) -> ObjectVar[SQLA_TYPE]: ...

    if TYPE_CHECKING:

        @overload
        def __get__(
            self: Field[DATACLASS_TYPE] | Field[DATACLASS_TYPE | None],
            instance: None,
            owner: Any,
        ) -> ObjectVar[DATACLASS_TYPE]: ...

    @overload
    def __get__(self, instance: None, owner: Any) -> Var[FIELD_TYPE]: ...

    @overload
    def __get__(self, instance: Any, owner: Any) -> FIELD_TYPE: ...

    def __get__(self, instance: Any, owner: Any):  # pyright: ignore [reportInconsistentOverload]
        """Get the Var.

        Args:
            instance: The instance of the class accessing the Var.
            owner: The class that the Var is attached to.
        """


@overload
def field(
    default: FIELD_TYPE | _MISSING_TYPE = MISSING,
    *,
    is_var: Literal[False],
    default_factory: Callable[[], FIELD_TYPE] | None = None,
) -> FIELD_TYPE: ...


@overload
def field(
    default: FIELD_TYPE | _MISSING_TYPE = MISSING,
    *,
    default_factory: Callable[[], FIELD_TYPE] | None = None,
    is_var: Literal[True] = True,
) -> Field[FIELD_TYPE]: ...


def field(
    default: FIELD_TYPE | _MISSING_TYPE = MISSING,
    *,
    default_factory: Callable[[], FIELD_TYPE] | None = None,
    is_var: bool = True,
) -> Field[FIELD_TYPE] | FIELD_TYPE:
    """Create a field for a state.

    Args:
        default: The default value for the field.
        default_factory: The default factory for the field.
        is_var: Whether the field is a Var.

    Returns:
        The field for the state.

    Raises:
        ValueError: If both default and default_factory are specified.
    """
    if default is not MISSING and default_factory is not None:
        msg = "cannot specify both default and default_factory"
        raise ValueError(msg)
    if default is not MISSING and not types.is_immutable(default):
        console.warn(
            "Mutable default values are not recommended. "
            "Use default_factory instead to avoid unexpected behavior."
        )
        return Field(
            default_factory=functools.partial(copy.deepcopy, default),
            is_var=is_var,
        )
    return Field(
        default=default,
        default_factory=default_factory,
        is_var=is_var,
    )


@dataclass_transform(kw_only_default=True, field_specifiers=(field,))
class BaseStateMeta(ABCMeta):
    """Meta class for BaseState."""

    if TYPE_CHECKING:
        __inherited_fields__: Mapping[str, Field]
        __own_fields__: dict[str, Field]
        __fields__: dict[str, Field]

        # Whether this state class is a mixin and should not be instantiated.
        _mixin: bool = False

    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        mixin: bool = False,
    ) -> type:
        """Create a new class.

        Args:
            name: The name of the class.
            bases: The bases of the class.
            namespace: The namespace of the class.
            mixin: Whether the class is a mixin and should not be instantiated.

        Returns:
            The new class.
        """
        state_bases = [
            base for base in bases if issubclass(base, EvenMoreBasicBaseState)
        ]
        mixin = mixin or (
            bool(state_bases) and all(base._mixin for base in state_bases)
        )
        # Add the field to the class
        inherited_fields: dict[str, Field] = {}
        own_fields: dict[str, Field] = {}
        resolved_annotations = types.resolve_annotations(
            annotations_from_namespace(namespace), namespace["__module__"]
        )

        for base in bases[::-1]:
            if hasattr(base, "__inherited_fields__"):
                inherited_fields.update(base.__inherited_fields__)
        for base in bases[::-1]:
            if hasattr(base, "__own_fields__"):
                inherited_fields.update(base.__own_fields__)

        for key, value in [
            (key, value)
            for key, value in namespace.items()
            if key not in resolved_annotations
        ]:
            if isinstance(value, Field):
                if value.annotated_type is not Any:
                    new_value = value
                elif value.default is not MISSING:
                    new_value = Field(
                        default=value.default,
                        is_var=value.is_var,
                        annotated_type=figure_out_type(value.default),
                    )
                else:
                    new_value = Field(
                        default_factory=value.default_factory,
                        is_var=value.is_var,
                        annotated_type=Any,
                    )
            elif (
                not key.startswith("__")
                and not callable(value)
                and not isinstance(value, (staticmethod, classmethod, property, Var))
            ):
                if types.is_immutable(value):
                    new_value = Field(
                        default=value,
                        annotated_type=figure_out_type(value),
                    )
                else:
                    new_value = Field(
                        default_factory=functools.partial(copy.deepcopy, value),
                        annotated_type=figure_out_type(value),
                    )
            else:
                continue

            own_fields[key] = new_value

        for key, annotation in resolved_annotations.items():
            value = namespace.get(key, MISSING)

            if types.is_classvar(annotation):
                # If the annotation is a classvar, skip it.
                continue

            if value is MISSING:
                value = Field(
                    annotated_type=annotation,
                )
            elif not isinstance(value, Field):
                if types.is_immutable(value):
                    value = Field(
                        default=value,
                        annotated_type=annotation,
                    )
                else:
                    value = Field(
                        default_factory=functools.partial(copy.deepcopy, value),
                        annotated_type=annotation,
                    )
            else:
                value = Field(
                    default=value.default,
                    default_factory=value.default_factory,
                    is_var=value.is_var,
                    annotated_type=annotation,
                )

            own_fields[key] = value

        namespace["__own_fields__"] = own_fields
        namespace["__inherited_fields__"] = inherited_fields
        namespace["__fields__"] = inherited_fields | own_fields
        namespace["_mixin"] = mixin
        return super().__new__(cls, name, bases, namespace)


class EvenMoreBasicBaseState(metaclass=BaseStateMeta):
    """A simplified base state class that provides basic functionality."""

    def __init__(
        self,
        **kwargs,
    ):
        """Initialize the state with the given kwargs.

        Args:
            **kwargs: The kwargs to pass to the state.
        """
        super().__init__()
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)
        for name, value in type(self).get_fields().items():
            if name not in kwargs:
                default_value = value.default_value()
                object.__setattr__(self, name, default_value)

    def set(self, **kwargs):
        """Mutate the state by setting the given kwargs. Returns the state.

        Args:
            **kwargs: The kwargs to set.

        Returns:
            The state with the fields set to the given kwargs.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)
        return self

    @classmethod
    def get_fields(cls) -> Mapping[str, Field]:
        """Get the fields of the component.

        Returns:
            The fields of the component.
        """
        return cls.__fields__

    @classmethod
    def add_field(cls, name: str, var: Var, default_value: Any):
        """Add a field to the class after class definition.

        Used by State.add_var() to correctly handle the new variable.

        Args:
            name: The name of the field to add.
            var: The variable to add a field for.
            default_value: The default value of the field.
        """
        if types.is_immutable(default_value):
            new_field = Field(
                default=default_value,
                annotated_type=var._var_type,
            )
        else:
            new_field = Field(
                default_factory=functools.partial(copy.deepcopy, default_value),
                annotated_type=var._var_type,
            )
        cls.__fields__[name] = new_field


NUMBER_T = TypeVarExt(
    "NUMBER_T",
    bound=(int | float | Decimal),
    default=(int | float | Decimal),
    covariant=True,
)


def raise_unsupported_operand_types(
    operator: str, operands_types: tuple[type, ...]
) -> NoReturn:
    """Raise an unsupported operand types error.

    Args:
        operator: The operator.
        operands_types: The types of the operands.

    Raises:
        VarTypeError: The operand types are unsupported.
    """
    msg = f"Unsupported Operand type(s) for {operator}: {', '.join(t.__name__ for t in operands_types)}"
    raise VarTypeError(msg)


class NumberVar(Var[NUMBER_T], python_types=(int, float, Decimal)):
    """Type marker for immutable number vars.

    The behavior (operators, methods) is implemented by ``RustVar``; this class
    survives only to anchor the type registration and serve as an isinstance /
    ``.to(...)`` / annotation target.
    """


class BooleanVar(NumberVar[bool], python_types=bool):
    """Type marker for immutable boolean vars (see ``NumberVar``)."""


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class LiteralNumberVar(LiteralVar[NUMBER_T], NumberVar[NUMBER_T]):
    """Registry anchor for literal number vars; instances are ``RustLiteralVar``."""

    _var_value: float | int | Decimal = dataclasses.field(default=0)

    def json(self) -> str:
        """Get the JSON representation of the var.

        Returns:
            The JSON representation of the var.

        Raises:
            PrimitiveUnserializableToJSONError: If the var is unserializable to JSON.
        """
        if isinstance(self._var_value, Decimal):
            return json.dumps(float(self._var_value))
        if math.isinf(self._var_value) or math.isnan(self._var_value):
            msg = f"No valid JSON representation for {self}"
            raise PrimitiveUnserializableToJSONError(msg)
        return json.dumps(self._var_value)

    def __hash__(self) -> int:
        """Calculate the hash value of the object.

        Returns:
            int: The hash value of the object.
        """
        return hash((type(self).__name__, self._var_value))

    @classmethod
    def _get_all_var_data_without_creating_var(
        cls, value: float | int | Decimal
    ) -> VarData | None:
        """Get all the var data without creating the var.

        Args:
            value: The value of the var.

        Returns:
            The var data.
        """
        return None

    @classmethod
    def create(cls, value: float | int | Decimal, _var_data: VarData | None = None):
        """Create the number var.

        Args:
            value: The value of the var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The number var.
        """
        if math.isinf(value):
            js_expr = "Infinity" if value > 0 else "-Infinity"
        elif math.isnan(value):
            js_expr = "NaN"
        else:
            js_expr = str(value)

        return cls(
            _js_expr=js_expr,
            _var_type=type(value),
            _var_data=_var_data,
            _var_value=value,
        )


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class LiteralBooleanVar(LiteralVar[bool], BooleanVar):
    """Registry anchor for literal boolean vars; instances are ``RustLiteralVar``."""

    _var_value: bool = dataclasses.field(default=False)

    def json(self) -> str:
        """Get the JSON representation of the var.

        Returns:
            The JSON representation of the var.
        """
        return "true" if self._var_value else "false"

    def __hash__(self) -> int:
        """Calculate the hash value of the object.

        Returns:
            int: The hash value of the object.
        """
        return hash((type(self).__name__, self._var_value))

    @classmethod
    def _get_all_var_data_without_creating_var(cls, value: bool) -> VarData | None:
        """Get all the var data without creating the var.

        Args:
            value: The value of the var.

        Returns:
            The var data.
        """
        return None

    @classmethod
    def create(cls, value: bool, _var_data: VarData | None = None):
        """Create the boolean var.

        Args:
            value: The value of the var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The boolean var.
        """
        return cls(
            _js_expr="true" if value else "false",
            _var_type=bool,
            _var_data=_var_data,
            _var_value=value,
        )


_IS_TRUE_IMPORT: ImportDict = {
    f"$/{constants.Dirs.STATE_PATH}": [ImportVar(tag="isTrue")],
}

_IS_NOT_NULL_OR_UNDEFINED_IMPORT: ImportDict = {
    f"$/{constants.Dirs.STATE_PATH}": [ImportVar(tag="isNotNullOrUndefined")],
}


def comparison_operator(
    func: Callable[[Var, Var], str],
) -> Callable[[Var | Any, Var | Any], BooleanVar]:
    """Decorator to create a comparison operation.

    Args:
        func: The comparison operation function.

    Returns:
        The comparison operation.
    """

    @var_operation
    def operation(lhs: Var, rhs: Var):
        return var_operation_return(
            js_expression=func(lhs, rhs),
            var_type=bool,
        )

    def wrapper(lhs: Var | Any, rhs: Var | Any) -> BooleanVar:
        """Create the comparison operation.

        Args:
            lhs: The first value.
            rhs: The second value.

        Returns:
            The comparison operation.
        """
        return operation(lhs, rhs)

    return wrapper


@comparison_operator
def equal_operation(lhs: Var, rhs: Var):
    """Equal comparison.

    Args:
        lhs: The first value.
        rhs: The second value.

    Returns:
        The result of the comparison.
    """
    return f"({lhs}?.valueOf?.() === {rhs}?.valueOf?.())"


@var_operation
def boolify(value: Var):
    """Convert the value to a boolean.

    Args:
        value: The value.

    Returns:
        The boolean value.
    """
    return var_operation_return(
        js_expression=f"isTrue({value})",
        var_type=bool,
        var_data=VarData(imports=_IS_TRUE_IMPORT),
    )


@var_operation
def is_not_none_operation(value: Var):
    """Check if the value is not None.

    Args:
        value: The value.

    Returns:
        The boolean value.
    """
    return var_operation_return(
        js_expression=f"isNotNullOrUndefined({value})",
        var_type=bool,
        var_data=VarData(imports=_IS_NOT_NULL_OR_UNDEFINED_IMPORT),
    )


@var_operation
def ternary_operation(
    condition: Var[bool], if_true: Var[T], if_false: Var[U]
) -> CustomVarOperationReturn[T | U]:
    """Create a ternary operation.

    Args:
        condition: The condition.
        if_true: The value if the condition is true.
        if_false: The value if the condition is false.

    Returns:
        The ternary operation.
    """
    type_value: type[T] | type[U] = unionize(if_true._var_type, if_false._var_type)
    value: CustomVarOperationReturn[T | U] = var_operation_return(
        js_expression=f"({condition} ? {if_true} : {if_false})",
        var_type=type_value,
    )
    return value


NUMBER_TYPES = (int, float, Decimal, NumberVar)


OBJECT_TYPE = TypeVar("OBJECT_TYPE", covariant=True)


def _determine_value_type(var_type: GenericType):
    """Resolve the value type of a mapping/dataclass/typeddict var type.

    Args:
        var_type: The object var's type.

    Returns:
        The unionized value type (``Any`` when undeterminable).
    """
    origin_var_type = get_origin(var_type) or var_type

    if origin_var_type in types.UnionTypes:
        return unionize(*[
            _determine_value_type(arg)
            for arg in get_args(var_type)
            if arg is not type(None)
        ])

    if is_typeddict(origin_var_type) or dataclasses.is_dataclass(origin_var_type):
        annotations = get_type_hints(origin_var_type)
        return unionize(*annotations.values())

    if origin_var_type in (dict, Mapping):
        args = get_args(var_type)
        return args[1] if args else Any

    return Any


_OBJECT_PYTHON_TYPES = (Mapping,)
if find_spec("pydantic"):
    import pydantic

    _OBJECT_PYTHON_TYPES += (pydantic.BaseModel,)


class ObjectVar(Var[OBJECT_TYPE], python_types=_OBJECT_PYTHON_TYPES):
    """Type marker for immutable object vars (behavior is in ``RustVar``)."""


class RestProp(ObjectVar[dict[str, Any]]):
    """A special object var representing forwarded rest props."""


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class LiteralObjectVar(
    CachedVarOperation, ObjectVar[OBJECT_TYPE], LiteralVar[OBJECT_TYPE]
):
    """Registry anchor for literal object vars; plain dicts mint a RustLiteralVar."""

    _var_value: Mapping[Var | Any, Var | Any] = dataclasses.field(default_factory=dict)

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """The name of the var.

        Returns:
            The name of the var.
        """
        return (
            "({ "
            + ", ".join([
                f"[{LiteralVar.create(key)!s}] : {LiteralVar.create(value)!s}"
                for key, value in self._var_value.items()
            ])
            + " })"
        )

    def json(self) -> str:
        """Get the JSON representation of the object.

        Returns:
            The JSON representation of the object.

        Raises:
            TypeError: The keys and values of the object must be literal vars to get the JSON representation
        """
        keys_and_values = []
        for key, value in self._var_value.items():
            key = LiteralVar.create(key)
            value = LiteralVar.create(value)
            if not isinstance(key, LiteralVar) or not isinstance(value, LiteralVar):
                msg = "The keys and values of the object must be literal vars to get the JSON representation."
                raise TypeError(msg)
            keys_and_values.append(f"{key.json()}:{value.json()}")
        return "{" + ", ".join(keys_and_values) + "}"

    def __hash__(self) -> int:
        """Get the hash of the var.

        Returns:
            The hash of the var.
        """
        return hash((type(self).__name__, self._js_expr))

    @classmethod
    def _get_all_var_data_without_creating_var(
        cls,
        value: Mapping,
    ) -> VarData | None:
        """Get all the var data without creating a var.

        Args:
            value: The value to get the var data from.

        Returns:
            The var data.
        """
        return VarData.merge(
            LiteralArrayVar._get_all_var_data_without_creating_var(value),
            LiteralArrayVar._get_all_var_data_without_creating_var(value.values()),
        )

    @cached_property_no_lock
    def _cached_get_all_var_data(self) -> VarData | None:
        """Get all the var data.

        Returns:
            The var data.
        """
        return VarData.merge(
            LiteralArrayVar._get_all_var_data_without_creating_var(self._var_value),
            LiteralArrayVar._get_all_var_data_without_creating_var(
                self._var_value.values()
            ),
            self._var_data,
        )

    @classmethod
    def create(
        cls,
        _var_value: Mapping,
        _var_type: type[OBJECT_TYPE] | None = None,
        _var_data: VarData | None = None,
    ) -> LiteralObjectVar[OBJECT_TYPE]:
        """Create the literal object var.

        Args:
            _var_value: The value of the var.
            _var_type: The type of the var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The literal object var.

        Raises:
            TypeError: If the value is not a mapping type or a dataclass.
        """
        if not isinstance(_var_value, Mapping):
            from reflex_base.utils.serializers import serialize

            serialized = serialize(_var_value, get_type=False)
            if not isinstance(serialized, Mapping):
                msg = f"Expected a mapping type or a dataclass, got {_var_value!r} of type {type(_var_value).__name__}."
                raise TypeError(msg)

            return LiteralObjectVar(
                _js_expr="",
                _var_type=(type(_var_value) if _var_type is None else _var_type),
                _var_data=_var_data,
                _var_value=serialized,
            )

        return LiteralObjectVar(
            _js_expr="",
            _var_type=(figure_out_type(_var_value) if _var_type is None else _var_type),
            _var_data=_var_data,
            _var_value=_var_value,
        )


ARRAY_VAR_TYPE = TypeVar("ARRAY_VAR_TYPE", bound=Sequence, covariant=True)
OTHER_ARRAY_VAR_TYPE = TypeVar("OTHER_ARRAY_VAR_TYPE", bound=Sequence, covariant=True)
STRING_TYPE = TypeVarExt("STRING_TYPE", default=str, covariant=True)


class ArrayVar(Var[ARRAY_VAR_TYPE], python_types=(Sequence, set)):
    """Type marker for immutable array vars (behavior is in ``RustVar``)."""


class StringVar(Var[STRING_TYPE], python_types=str):
    """Type marker for immutable string vars (behavior is in ``RustVar``)."""


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class LiteralArrayVar(
    CachedVarOperation, LiteralVar[ARRAY_VAR_TYPE], ArrayVar[ARRAY_VAR_TYPE]
):
    """Registry anchor for literal array vars; plain lists mint a RustLiteralVar."""

    _var_value: Sequence[Var | Any] = dataclasses.field(default=())

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """The name of the var.

        Returns:
            The name of the var.
        """
        return (
            "["
            + ", ".join([
                str(LiteralVar.create(element)) for element in self._var_value
            ])
            + "]"
        )

    @classmethod
    def _get_all_var_data_without_creating_var(cls, value: Iterable) -> VarData | None:
        """Get all the VarData associated with the Var without creating a Var.

        Args:
            value: The value to get the VarData for.

        Returns:
            The VarData associated with the Var.
        """
        return VarData.merge(*[
            LiteralVar._get_all_var_data_without_creating_var_dispatch(element)
            for element in value
        ])

    @cached_property_no_lock
    def _cached_get_all_var_data(self) -> VarData | None:
        """Get all the VarData associated with the Var.

        Returns:
            The VarData associated with the Var.
        """
        return VarData.merge(
            *[
                LiteralVar._get_all_var_data_without_creating_var_dispatch(element)
                for element in self._var_value
            ],
            self._var_data,
        )

    def __hash__(self) -> int:
        """Get the hash of the var.

        Returns:
            The hash of the var.
        """
        return hash((self.__class__.__name__, self._js_expr))

    def json(self) -> str:
        """Get the JSON representation of the var.

        Returns:
            The JSON representation of the var.

        Raises:
            TypeError: If the array elements are not of type LiteralVar.
        """
        elements = []
        for element in self._var_value:
            element_var = LiteralVar.create(element)
            if not isinstance(element_var, LiteralVar):
                msg = f"Array elements must be of type LiteralVar, not {type(element_var)}"
                raise TypeError(msg)
            elements.append(element_var.json())

        return "[" + ", ".join(elements) + "]"

    @classmethod
    def create(
        cls,
        value: OTHER_ARRAY_VAR_TYPE,
        _var_type: type[OTHER_ARRAY_VAR_TYPE] | None = None,
        _var_data: VarData | None = None,
    ) -> LiteralArrayVar[OTHER_ARRAY_VAR_TYPE]:
        """Create a var from a string value.

        Args:
            value: The value to create the var from.
            _var_type: The type of the var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The var.
        """
        return LiteralArrayVar(
            _js_expr="",
            _var_type=figure_out_type(value) if _var_type is None else _var_type,
            _var_data=_var_data,
            _var_value=value,
        )


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class LiteralStringVar(LiteralVar[STRING_TYPE], StringVar[STRING_TYPE]):
    """Registry anchor for literal string vars; plain strings mint a RustLiteralVar."""

    _var_value: str = dataclasses.field(default="")

    @classmethod
    def _get_all_var_data_without_creating_var(cls, value: str) -> VarData | None:
        """Get all the VarData associated with the Var without creating a Var.

        Args:
            value: The value to get the VarData for.

        Returns:
            The VarData associated with the Var.
        """
        if constants.REFLEX_VAR_OPENING_TAG not in value:
            return None
        return cls.create(value)._get_all_var_data()

    @classmethod
    def create(
        cls,
        value: str,
        _var_type: GenericType | None = None,
        _var_data: VarData | None = None,
    ) -> StringVar:
        """Create a var from a string value.

        Args:
            value: The value to create the var from.
            _var_type: The type of the var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The var.
        """
        # Determine var type in case the value is inherited from str.
        _var_type = _var_type or type(value) or str

        if constants.REFLEX_VAR_OPENING_TAG in value:
            strings_and_vals: list[Var | str] = []
            offset = 0

            # Find all tags
            while m := _decode_var_pattern.search(value):
                start, end = m.span()

                strings_and_vals.append(value[:start])

                serialized_data = m.group(1)

                if serialized_data.isnumeric() or (
                    serialized_data[0] == "-" and serialized_data[1:].isnumeric()
                ):
                    # This is a global immutable var.
                    var = _global_vars[int(serialized_data)]
                    strings_and_vals.append(var)
                    value = value[(end + len(var._js_expr)) :]

                offset += end - start

            strings_and_vals.append(value)

            filtered_strings_and_vals = [
                s for s in strings_and_vals if isinstance(s, Var) or s
            ]
            if len(filtered_strings_and_vals) == 1:
                only_string = filtered_strings_and_vals[0]
                if isinstance(only_string, str):
                    return LiteralVar.create(only_string).to(StringVar, _var_type)
                return only_string.to(StringVar, only_string._var_type)

            if len(
                literal_strings := [
                    s
                    for s in filtered_strings_and_vals
                    if isinstance(s, str) or var_isinstance(s, LiteralStringVar)
                ]
            ) == len(filtered_strings_and_vals):
                return LiteralStringVar.create(
                    "".join(
                        s._var_value if var_isinstance(s, LiteralStringVar) else s
                        for s in literal_strings
                    ),
                    _var_type=_var_type,
                    _var_data=VarData.merge(
                        _var_data,
                        *(
                            s._get_all_var_data()
                            for s in filtered_strings_and_vals
                            if isinstance(s, Var)
                        ),
                    ),
                )

            concat_result = ConcatVarOperation.create(
                *filtered_strings_and_vals,
                _var_data=_var_data,
            )

            return (
                concat_result
                if _var_type is str
                else concat_result.to(StringVar, _var_type)
            )

        return LiteralStringVar(
            _js_expr=json.dumps(value),
            _var_type=_var_type,
            _var_data=_var_data,
            _var_value=value,
        )

    def __hash__(self) -> int:
        """Get the hash of the var.

        Returns:
            The hash of the var.
        """
        return hash((type(self).__name__, self._var_value))

    def json(self) -> str:
        """Get the JSON representation of the var.

        Returns:
            The JSON representation of the var.
        """
        return json.dumps(self._var_value)


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class ConcatVarOperation(CachedVarOperation, StringVar[str]):
    """Representing a concatenation of literal string vars."""

    _var_value: tuple[Var, ...] = dataclasses.field(default_factory=tuple)

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """The name of the var.

        Returns:
            The name of the var.
        """
        list_of_strs: list[str | Var] = []
        last_string = ""
        for var in self._var_value:
            if var_isinstance(var, LiteralStringVar):
                last_string += var._var_value
            else:
                if last_string:
                    list_of_strs.append(last_string)
                    last_string = ""
                list_of_strs.append(var)

        if last_string:
            list_of_strs.append(last_string)

        list_of_strs_filtered = [
            str(LiteralVar.create(s)) for s in list_of_strs if isinstance(s, Var) or s
        ]

        if len(list_of_strs_filtered) == 1:
            return list_of_strs_filtered[0]

        return "(" + "+".join(list_of_strs_filtered) + ")"

    @cached_property_no_lock
    def _cached_get_all_var_data(self) -> VarData | None:
        """Get all the VarData associated with the Var.

        Returns:
            The VarData associated with the Var.
        """
        return VarData.merge(
            *[
                var._get_all_var_data()
                for var in self._var_value
                if isinstance(var, Var)
            ],
            self._var_data,
        )

    @classmethod
    def create(
        cls,
        *value: Var | str,
        _var_data: VarData | None = None,
    ) -> ConcatVarOperation:
        """Create a var from a string value.

        Args:
            *value: The values to concatenate.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The var.
        """
        return cls(
            _js_expr="",
            _var_type=str,
            _var_data=_var_data,
            _var_value=tuple(map(LiteralVar.create, value)),
        )


def _determine_value_of_array_index(
    var_type: GenericType, index: int | float | Decimal | None = None
):
    """Determine the element type of an array index.

    Args:
        var_type: The type of the array.
        index: The index of the array.

    Returns:
        The value of the array index.
    """
    origin_var_type = get_origin(var_type) or var_type
    if origin_var_type in types.UnionTypes:
        return unionize(*[
            _determine_value_of_array_index(t, index)
            for t in get_args(var_type)
            if t is not type(None)
        ])
    if origin_var_type is range:
        return int
    if origin_var_type in (Sequence, Iterable, list, set):
        args = get_args(var_type)
        return args[0] if args else Any
    if origin_var_type is tuple:
        args = get_args(var_type)
        if len(args) == 2 and args[1] is ...:
            return args[0]
        return (
            args[int(index) % len(args)]
            if args and index is not None
            else (unionize(*args) if args else Any)
        )
    return Any


@var_operation
def string_replace_operation(
    string: StringVar[Any], search_value: StringVar | str, new_value: StringVar | str
):
    """Replace a string with a value.

    Args:
        string: The string.
        search_value: The string to search.
        new_value: The value to be replaced with.

    Returns:
        The string replace operation.
    """
    return var_operation_return(
        js_expression=f"{string}.replaceAll({search_value}, {new_value})",
        var_type=str,
    )


V1 = TypeVar("V1")
V2 = TypeVar("V2")
V3 = TypeVar("V3")
V4 = TypeVar("V4")
V5 = TypeVar("V5")
V6 = TypeVar("V6")
R = TypeVar("R")


class ReflexCallable(Protocol[P, R]):
    """Protocol for a callable."""

    __call__: Callable[P, R]


CALLABLE_TYPE = TypeVar("CALLABLE_TYPE", bound=ReflexCallable, covariant=True)
OTHER_CALLABLE_TYPE = TypeVar(
    "OTHER_CALLABLE_TYPE", bound=ReflexCallable, covariant=True
)


def _is_js_identifier_start(char: str) -> bool:
    """Check whether a character can start a JavaScript identifier.

    Returns:
        True if the character is valid as the first character of a JS identifier.
    """
    return char == "$" or char == "_" or char.isalpha()


def _is_js_identifier_char(char: str) -> bool:
    """Check whether a character can continue a JavaScript identifier.

    Returns:
        True if the character is valid within a JS identifier.
    """
    return _is_js_identifier_start(char) or char.isdigit()


def _starts_with_arrow_function(expr: str) -> bool:
    """Check whether an expression starts with an inline arrow function.

    Returns:
        True if the expression begins with an arrow function.
    """
    if "=>" not in expr:
        return False

    expr = expr.lstrip()
    if not expr:
        return False

    if expr.startswith("async"):
        async_remainder = expr[len("async") :]
        if async_remainder[:1].isspace():
            expr = async_remainder.lstrip()

    if not expr:
        return False

    if _is_js_identifier_start(expr[0]):
        end_index = 1
        while end_index < len(expr) and _is_js_identifier_char(expr[end_index]):
            end_index += 1
        return expr[end_index:].lstrip().startswith("=>")

    if not expr.startswith("("):
        return False

    depth = 0
    string_delimiter: str | None = None
    escaped = False

    for index, char in enumerate(expr):
        if string_delimiter is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_delimiter:
                string_delimiter = None
            continue

        if char in {"'", '"', "`"}:
            string_delimiter = char
            continue

        if char == "(":
            depth += 1
            continue

        if char == ")":
            depth -= 1
            if depth == 0:
                return expr[index + 1 :].lstrip().startswith("=>")

    return False


class FunctionVar(Var[CALLABLE_TYPE], default_type=ReflexCallable[Any, Any]):
    """Base class for immutable function vars."""

    def partial(self, *args: Var | Any) -> FunctionVar:
        """Partially apply the function with the given arguments.

        Args:
            *args: The arguments to partially apply the function with.

        Returns:
            The partially applied function.
        """
        if not args:
            return self
        return ArgsFunctionOperation.create(
            ("...args",),
            VarOperationCall.create(self, *args, Var(_js_expr="...args")),
        )

    def call(self, *args: Var | Any) -> Var:
        """Call the function with the given arguments.

        Args:
            *args: The arguments to call the function with.

        Returns:
            The function call operation.
        """
        return VarOperationCall.create(self, *args).guess_type()

    __call__ = call


class BuilderFunctionVar(
    FunctionVar[CALLABLE_TYPE], default_type=ReflexCallable[Any, Any]
):
    """Base class for immutable function vars with the builder pattern."""

    __call__ = FunctionVar.partial


class FunctionStringVar(FunctionVar[CALLABLE_TYPE]):
    """Base class for immutable function vars from a string."""

    @classmethod
    def create(
        cls,
        func: str,
        _var_type: type[OTHER_CALLABLE_TYPE] = ReflexCallable[Any, Any],
        _var_data: VarData | None = None,
    ) -> FunctionStringVar[OTHER_CALLABLE_TYPE]:
        """Create a new function var from a string.

        Args:
            func: The function to call.
            _var_type: The type of the Var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The function var.
        """
        return FunctionStringVar(
            _js_expr=func,
            _var_type=_var_type,
            _var_data=_var_data,
        )


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class VarOperationCall(Generic[P, R], CachedVarOperation, Var[R]):
    """Base class for immutable vars that are the result of a function call."""

    _func: FunctionVar[ReflexCallable[P, R]] | None = dataclasses.field(default=None)
    _args: tuple[Var | Any, ...] = dataclasses.field(default_factory=tuple)

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """The name of the var.

        Returns:
            The name of the var.
        """
        func_expr = str(self._func)
        if _starts_with_arrow_function(func_expr) and not format.is_wrapped(
            func_expr, "("
        ):
            func_expr = format.wrap(func_expr, "(")

        return f"({func_expr}({', '.join([str(LiteralVar.create(arg)) for arg in self._args])}))"

    @cached_property_no_lock
    def _cached_get_all_var_data(self) -> VarData | None:
        """Get all the var data associated with the var.

        Returns:
            All the var data associated with the var.
        """
        return VarData.merge(
            self._func._get_all_var_data() if self._func is not None else None,
            *[LiteralVar.create(arg)._get_all_var_data() for arg in self._args],
            self._var_data,
        )

    @classmethod
    def create(
        cls,
        func: FunctionVar[ReflexCallable[P, R]],
        *args: Var | Any,
        _var_type: GenericType = Any,
        _var_data: VarData | None = None,
    ) -> VarOperationCall:
        """Create a new function call var.

        Args:
            func: The function to call.
            *args: The arguments to call the function with.
            _var_type: The type of the Var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The function call var.
        """
        function_return_type = (
            func._var_type.__args__[1]
            if getattr(func._var_type, "__args__", None)
            else Any
        )
        var_type = _var_type if _var_type is not Any else function_return_type
        return cls(
            _js_expr="",
            _var_type=var_type,
            _var_data=_var_data,
            _func=func,
            _args=args,
        )


@dataclasses.dataclass(frozen=True)
class DestructuredArg:
    """Class for destructured arguments."""

    fields: tuple[str, ...] = ()
    rest: str | None = None

    def to_javascript(self) -> str:
        """Convert the destructured argument to JavaScript.

        Returns:
            The destructured argument in JavaScript.
        """
        inner = ", ".join(self.fields)
        if self.rest:
            inner = f"{inner}, ...{self.rest}" if inner else f"...{self.rest}"
        return format.wrap(inner, "{", "}")


@dataclasses.dataclass(frozen=True)
class FunctionArgs:
    """Class for function arguments."""

    args: tuple[str | DestructuredArg, ...] = ()
    rest: str | None = None


def format_args_function_operation(
    args: FunctionArgs, return_expr: Var | Any, explicit_return: bool
) -> str:
    """Format an args function operation.

    Args:
        args: The function arguments.
        return_expr: The return expression.
        explicit_return: Whether to use explicit return syntax.

    Returns:
        The formatted args function operation.
    """
    arg_parts = [
        arg if isinstance(arg, str) else arg.to_javascript() for arg in args.args
    ]
    if args.rest:
        arg_parts.append(f"...{args.rest}")
    arg_names_str = ", ".join(arg_parts)

    return_expr_str = str(LiteralVar.create(return_expr))

    # Wrap return expression in curly braces if explicit return syntax is used.
    return_expr_str_wrapped = (
        format.wrap(return_expr_str, "{", "}") if explicit_return else return_expr_str
    )

    return f"(({arg_names_str}) => {return_expr_str_wrapped})"


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class ArgsFunctionOperation(CachedVarOperation, FunctionVar):
    """Base class for immutable function defined via arguments and return expression."""

    _args: FunctionArgs = dataclasses.field(default_factory=FunctionArgs)
    _return_expr: Var | Any = dataclasses.field(default=None)
    _explicit_return: bool = dataclasses.field(default=False)

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """The name of the var.

        Returns:
            The name of the var.
        """
        return format_args_function_operation(
            self._args, self._return_expr, self._explicit_return
        )

    @classmethod
    def create(
        cls,
        args_names: Sequence[str | DestructuredArg],
        return_expr: Var | Any,
        rest: str | None = None,
        explicit_return: bool = False,
        _var_type: GenericType = Callable,
        _var_data: VarData | None = None,
    ):
        """Create a new function var.

        Args:
            args_names: The names of the arguments.
            return_expr: The return expression of the function.
            rest: The name of the rest argument.
            explicit_return: Whether to use explicit return syntax.
            _var_type: The type of the Var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The function var.
        """
        return_expr = Var.create(return_expr)
        return cls(
            _js_expr="",
            _var_type=_var_type,
            _var_data=_var_data,
            _args=FunctionArgs(args=tuple(args_names), rest=rest),
            _return_expr=return_expr,
            _explicit_return=explicit_return,
        )


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class ArgsFunctionOperationBuilder(CachedVarOperation, BuilderFunctionVar):
    """Base class for immutable function defined via arguments and return expression with the builder pattern."""

    _args: FunctionArgs = dataclasses.field(default_factory=FunctionArgs)
    _return_expr: Var | Any = dataclasses.field(default=None)
    _explicit_return: bool = dataclasses.field(default=False)

    @cached_property_no_lock
    def _cached_var_name(self) -> str:
        """The name of the var.

        Returns:
            The name of the var.
        """
        return format_args_function_operation(
            self._args, self._return_expr, self._explicit_return
        )

    @classmethod
    def create(
        cls,
        args_names: Sequence[str | DestructuredArg],
        return_expr: Var | Any,
        rest: str | None = None,
        explicit_return: bool = False,
        _var_type: GenericType = Callable,
        _var_data: VarData | None = None,
    ):
        """Create a new function var.

        Args:
            args_names: The names of the arguments.
            return_expr: The return expression of the function.
            rest: The name of the rest argument.
            explicit_return: Whether to use explicit return syntax.
            _var_type: The type of the Var.
            _var_data: Additional hooks and imports associated with the Var.

        Returns:
            The function var.
        """
        return_expr = Var.create(return_expr)
        return cls(
            _js_expr="",
            _var_type=_var_type,
            _var_data=_var_data,
            _args=FunctionArgs(args=tuple(args_names), rest=rest),
            _return_expr=return_expr,
            _explicit_return=explicit_return,
        )


JSON_STRINGIFY = FunctionStringVar.create(
    "JSON.stringify", _var_type=ReflexCallable[[Any], str]
)
ARRAY_ISARRAY = FunctionStringVar.create(
    "Array.isArray", _var_type=ReflexCallable[[Any], bool]
)
PROTOTYPE_TO_STRING = FunctionStringVar.create(
    "((__to_string) => __to_string.toString())",
    _var_type=ReflexCallable[[Any], str],
)


# Register the Rust var implementations as virtual subclasses of the Python
# ``Var`` / ``LiteralVar`` bases (``MetaclassVar`` is an ``ABCMeta``). This makes
# ``isinstance(rust_var, Var)`` / ``isinstance(rust_literal, LiteralVar)`` native,
# cached checks — replacing the former custom ``__instancecheck__`` bridge.
Var.register(RustVar)
LiteralVar.register(RustLiteralVar)
