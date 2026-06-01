"""Capture the current Python ``Var`` system's rendered output as golden fixtures.

This is the **correctness oracle for the Rust Var cutover**. The hard cutover
deletes the Python ``Var`` implementation; once it is gone there is nothing
left to diff the Rust ``Var`` against. So before any rip, this script freezes
the existing behaviour: it replays the shared expression corpus
(``tests/units/vars/_var_corpus.py``) and records, per expression, the exact
``_js_expr`` / ``_var_type`` / ``_get_all_var_data()`` the Python Var produces.

Run: ``uv run python scripts/capture_var_golden.py`` (writes
``tests/units/vars/var_golden.json``). The Rust rebuild is validated by
replaying the same corpus and asserting byte-identical output against this
file (``test_var_golden_parity.py``). Regenerate ONLY from a known-good Python
Var (i.e. before the rip, or from a tagged baseline) — never from a
half-migrated tree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = REPO_ROOT / "tests/units/vars/var_golden.json"

# Import the corpus under its canonical dotted path so the state-name mangling
# matches the parity gate exactly (see _var_corpus module docstring).
sys.path.insert(0, str(REPO_ROOT))
from tests.units.vars._var_corpus import _corpus, _record  # noqa: E402


def main() -> int:
    """Build the corpus, capture each Var, and write the golden JSON.

    Returns:
        Process exit code (always 0).
    """
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, build in _corpus().items():
        try:
            out[key] = _record(build())
        except Exception as e:  # report, don't abort
            errors[key] = f"{type(e).__name__}: {e}"

    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"captured {len(out)} expressions -> {GOLDEN_PATH}")
    if errors:
        print(f"\n{len(errors)} builders raised (excluded from golden):")
        for k, msg in sorted(errors.items()):
            print(f"  {k}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
