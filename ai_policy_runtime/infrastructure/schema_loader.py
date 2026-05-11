from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SchemaLoader:
    """Load bundled JSON Schemas by stable logical name."""

    def __init__(self, root: str | Path = "schemas") -> None:
        self.root = Path(root)

    def load(self, name: str) -> dict[str, Any]:
        path = self.root / f"{name}.schema.json"
        if not path.exists():
            raise FileNotFoundError(f"Schema not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
