"""Re-export from reflex_base.

The Python number-var implementation has been replaced by the Rust ``RustVar``;
the surviving type markers and helper operations now live in
``reflex_base.vars.base``.
"""

from reflex_base.vars.base import (
    NUMBER_TYPES,
    BooleanVar,
    LiteralBooleanVar,
    LiteralNumberVar,
    NumberVar,
    boolify,
    equal_operation,
    is_not_none_operation,
    raise_unsupported_operand_types,
    ternary_operation,
)

__all__ = [
    "NUMBER_TYPES",
    "BooleanVar",
    "LiteralBooleanVar",
    "LiteralNumberVar",
    "NumberVar",
    "boolify",
    "equal_operation",
    "is_not_none_operation",
    "raise_unsupported_operand_types",
    "ternary_operation",
]
