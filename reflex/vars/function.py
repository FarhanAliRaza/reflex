"""Re-export from reflex_base.

The Python function-var implementation has been replaced by the Rust
``RustVar`` (which provides ``call``); the surviving function-construction
machinery now lives in ``reflex_base.vars.base``.
"""

from reflex_base.vars.base import (
    ARRAY_ISARRAY,
    JSON_STRINGIFY,
    PROTOTYPE_TO_STRING,
    ArgsFunctionOperation,
    ArgsFunctionOperationBuilder,
    DestructuredArg,
    FunctionStringVar,
    FunctionVar,
    VarOperationCall,
)

__all__ = [
    "ARRAY_ISARRAY",
    "JSON_STRINGIFY",
    "PROTOTYPE_TO_STRING",
    "ArgsFunctionOperation",
    "ArgsFunctionOperationBuilder",
    "DestructuredArg",
    "FunctionStringVar",
    "FunctionVar",
    "VarOperationCall",
]
