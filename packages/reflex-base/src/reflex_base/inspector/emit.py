"""Write the inspector source map to the public web directory."""

from __future__ import annotations

import json
from pathlib import Path

from . import capture, state


def write_source_map(public_dir: Path) -> Path | None:
    """Write the inspector source map under ``<public_dir>/__reflex/``.

    Args:
        public_dir: The static-served public directory, e.g. ``.web/public``.

    Returns:
        The path that was written, or ``None`` when the inspector is
        disabled.
    """
    if not state.is_enabled():
        return None

    from . import PUBLIC_DIRNAME, SOURCE_MAP_FILENAME

    payload = {
        str(cid): {
            "file": info.file,
            "line": info.line,
            "column": info.column,
            "component": info.component,
        }
        for cid, info in capture.snapshot().items()
    }
    out_path = Path(public_dir) / PUBLIC_DIRNAME / SOURCE_MAP_FILENAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    return out_path
