"""Write the inspector source map to the public web directory."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from . import capture, state

SOURCE_MAP_DIRNAME = "__reflex"
SOURCE_MAP_FILENAME = "source-map.json"


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

    payload = {
        str(cid): dataclasses.asdict(info) for cid, info in capture.snapshot().items()
    }
    out_dir = Path(public_dir) / SOURCE_MAP_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / SOURCE_MAP_FILENAME
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    return out_path
