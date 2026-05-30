"""Re-export from reflex_base.

The Python object-var implementation has been replaced by the Rust
``RustVar``; the surviving type markers now live in ``reflex_base.vars.base``.
"""

from reflex_base.vars.base import (
    LiteralObjectVar,
    ObjectVar,
    RestProp,
)

__all__ = [
    "LiteralObjectVar",
    "ObjectVar",
    "RestProp",
]
