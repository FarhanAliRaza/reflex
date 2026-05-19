"""IR layer between Reflex's Python Component classes and the Rust compiler.

This is the **phase-1 → phase-2 boundary**. Phase 1 (Python) finalizes the
Component tree and emits IR bytes; phase 2 (Rust) consumes the bytes and
produces JSX without ever calling back into Python.

* :mod:`schema` — wire-format constants (Component/Value discriminants,
  literal types, hook positions). Increment ``SCHEMA_VERSION`` for any
  breaking change.
* :mod:`builder` — programmatic builders that produce positional
  ``list``\\ s in the shape the Rust parser expects. Bottom-up
  construction; one ``msgpack.packb`` call at the top.
* :mod:`pack` — thin ``msgpack.packb`` wrappers (one call per blob, per
  the spike note in ``RUST_REWRITE_PLAN.md`` §1).
* :mod:`canonical` — content hashing for stable ``NodeId``\\ s.
"""

from reflex.compiler.ir import builder, canonical, pack, schema

__all__ = ["builder", "canonical", "pack", "schema"]
