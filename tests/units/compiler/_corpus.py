"""Shared loader for the snapshot codegen corpus.

``tests/codegen_corpus/_runner.py`` ``discover()`` executes each fixture's
``component.py`` (which may define ``rx.State`` subclasses). Running it from
more than one test module would re-execute those modules and re-register
the state classes, raising ``StateValueError``. Importing this module loads
the corpus exactly once and shares the resulting fixture list.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CORPUS_ROOT = Path(__file__).resolve().parents[2] / "codegen_corpus"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_shared_corpus_runner", _CORPUS_ROOT / "_runner.py"
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so `@dataclass` can resolve the module's globals
    # (Python 3.14 looks up `sys.modules[cls.__module__]`).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


FIXTURES = _load_runner().discover()
