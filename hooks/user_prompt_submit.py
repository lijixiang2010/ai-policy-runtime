from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(".policy") / "config.json"
FALSE_VALUES = {"0", "false", "no", "off"}


def main() -> int:
    payload = _read_payload()
    prompt = str(payload.get("prompt", ""))
    if not prompt.strip():
        return 0

    project_root = Path(payload.get("cwd") or ".").resolve()
    config = ProjectHookConfig.load(project_root)
    if not config.enabled:
        return 0

    config.apply_environment()

    try:
        additional_context = _resolve_effective_prompt(
            prompt,
            project_root,
            config.policy_root(project_root),
            config.packs,
        )
    except Exception as exc:
        additional_context = (
            "AI Policy Runtime hook could not generate Effective Rules for this turn. "
            f"Error: {type(exc).__name__}: {exc}"
        )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": additional_context,
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_payload() -> dict[str, object]:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return data


@dataclass(frozen=True)
class ProjectHookConfig:
    """Project-local Codex hook configuration with environment overrides."""

    enabled: bool = True
    packs: tuple[str, ...] = ()
    policy_root_value: str | Path = PLUGIN_ROOT
    auto_install: bool | None = None
    embedding_provider: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_timeout: str | None = None

    @classmethod
    def load(cls, project_root: Path) -> "ProjectHookConfig":
        return cls.from_mapping(_load_project_config(project_root))

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ProjectHookConfig":
        return cls(
            enabled=_coerce_enabled(data.get("enabled", True)),
            packs=_configured_packs(data),
            policy_root_value=os.environ.get("AI_POLICY_ROOT")
            or data.get("policyRoot")
            or PLUGIN_ROOT,
            auto_install=_optional_bool(data.get("autoInstall")),
            embedding_provider=_optional_string(data.get("embeddingProvider")),
            embedding_base_url=_optional_string(data.get("embeddingBaseUrl")),
            embedding_api_key=_optional_string(data.get("embeddingApiKey")),
            embedding_model=_optional_string(data.get("embeddingModel")),
            embedding_timeout=_optional_string(data.get("embeddingTimeout")),
        )

    def policy_root(self, project_root: Path) -> Path:
        path = Path(str(self.policy_root_value))
        if not path.is_absolute():
            path = project_root / path
        return path.resolve()

    def apply_environment(self) -> None:
        self._apply_env("AI_POLICY_EMBEDDING_PROVIDER", self.embedding_provider)
        self._apply_env("AI_POLICY_EMBEDDING_BASE_URL", self.embedding_base_url)
        self._apply_env("AI_POLICY_EMBEDDING_API_KEY", self.embedding_api_key)
        self._apply_env("AI_POLICY_EMBEDDING_MODEL", self.embedding_model)
        self._apply_env("AI_POLICY_EMBEDDING_TIMEOUT", self.embedding_timeout)
        if self.auto_install is not None and "AI_POLICY_AUTO_INSTALL" not in os.environ:
            os.environ["AI_POLICY_AUTO_INSTALL"] = "1" if self.auto_install else "0"

    @staticmethod
    def _apply_env(name: str, value: str | None) -> None:
        if value and name not in os.environ:
            os.environ[name] = value


def _resolve_effective_prompt(
    prompt: str,
    project_root: Path,
    policy_root: Path,
    packs: tuple[str, ...],
) -> str:
    _prepare_imports()

    from ai_policy_runtime import PolicyRuntime, RuntimeConfig

    runtime = PolicyRuntime(
        RuntimeConfig.from_values(
            root=project_root,
            policy_root=policy_root,
        )
    )
    result = runtime.resolve(prompt, packs)
    return (result.current / "effective-prompt.md").read_text(encoding="utf-8")


def _prepare_imports() -> None:
    if str(PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT))

    try:
        import ai_policy_runtime  # noqa: F401
        import jsonschema  # noqa: F401
        import yaml  # noqa: F401
    except ModuleNotFoundError:
        _bootstrap_package()
        import ai_policy_runtime  # noqa: F401
        import jsonschema  # noqa: F401
        import yaml  # noqa: F401


def _bootstrap_package() -> None:
    if os.environ.get("AI_POLICY_AUTO_INSTALL", "1") in {"0", "false", "False"}:
        raise RuntimeError(
            "Python dependencies are missing and AI_POLICY_AUTO_INSTALL is disabled."
        )
    if not (PLUGIN_ROOT / "pyproject.toml").exists():
        raise RuntimeError(f"pyproject.toml not found under plugin root: {PLUGIN_ROOT}")

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-e",
        str(PLUGIN_ROOT),
    ]
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _configured_packs(config: dict[str, Any]) -> tuple[str, ...]:
    if "AI_POLICY_PACKS" in os.environ:
        return _split_csv(os.environ.get("AI_POLICY_PACKS", ""))

    packs = config.get("packs", ())
    if isinstance(packs, str):
        return _split_csv(packs)
    if isinstance(packs, list):
        return tuple(str(item).strip() for item in packs if str(item).strip())
    return ()


def _load_project_config(project_root: Path) -> dict[str, Any]:
    path = project_root / CONFIG_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Policy config must be a JSON object: {path}")
    return data


def _coerce_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in FALSE_VALUES
    return bool(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in FALSE_VALUES
    return bool(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _enabled(config: dict[str, Any]) -> bool:
    """Compatibility helper for focused unit tests."""

    return ProjectHookConfig.from_mapping(config).enabled


if __name__ == "__main__":
    raise SystemExit(main())
