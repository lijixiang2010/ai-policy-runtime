from __future__ import annotations

from typing import Any

from ai_policy_runtime.domain.diagnostics import Diagnostic
from ai_policy_runtime.infrastructure.schema_loader import SchemaLoader


class JsonSchemaValidator:
    """Validate mappings with bundled JSON Schema files."""

    def __init__(self, loader: SchemaLoader | None = None) -> None:
        self._loader = loader or SchemaLoader()

    def validate(self, schema_name: str, data: dict[str, Any], path: str) -> list[Diagnostic]:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return [Diagnostic("E000", "jsonschema dependency is not installed", path)]

        schema = self._loader.load(schema_name)
        validator = Draft202012Validator(schema)
        return [
            Diagnostic(
                "E_SCHEMA",
                f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}",
                path,
            )
            for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path))
        ]
