from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MODEL_KEY = "multilingual-mini"


@dataclass(frozen=True)
class LocalModelSpec:
    """A known local embedding model that can be installed on demand."""

    key: str
    repo_id: str
    directory_name: str
    description: str

    def to_dict(self, root: Path) -> dict[str, Any]:
        path = root / "models" / self.directory_name
        return {
            "key": self.key,
            "repo_id": self.repo_id,
            "path": str(path),
            "installed": path.exists(),
            "description": self.description,
        }


KNOWN_MODELS: tuple[LocalModelSpec, ...] = (
    LocalModelSpec(
        key=DEFAULT_MODEL_KEY,
        repo_id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        directory_name="paraphrase-multilingual-MiniLM-L12-v2",
        description="Default multilingual sentence-transformers model for semantic matching.",
    ),
)


class LocalModelManager:
    """Install and inspect local embedding model assets under a policy root."""

    def __init__(self, policy_root: str | Path = ".") -> None:
        self.policy_root = Path(policy_root)

    def list(self) -> tuple[dict[str, Any], ...]:
        """Return known local models and installation status."""

        return tuple(spec.to_dict(self.policy_root) for spec in KNOWN_MODELS)

    def inspect(self, *, check_loadable: bool = False) -> tuple[dict[str, Any], ...]:
        """Return known local model status, optionally checking runtime loadability."""

        items = []
        for spec in KNOWN_MODELS:
            item = spec.to_dict(self.policy_root)
            if check_loadable:
                item["usable"] = False
                item["error"] = None
                item["next_step"] = None
                if not item["installed"]:
                    item["next_step"] = (
                        "Run: ai-policy embedding configure --provider local --install"
                    )
                else:
                    result = check_sentence_transformer_model(Path(str(item["path"])))
                    item.update(result)
            items.append(item)
        return tuple(items)

    def install(self, model: str = "default") -> dict[str, Any]:
        """Download a known local model into policy_root/models."""

        spec = _resolve_model(model)
        target = self.policy_root / "models" / spec.directory_name
        target.parent.mkdir(parents=True, exist_ok=True)
        _snapshot_download(spec.repo_id, target)
        return {
            "installed": True,
            "key": spec.key,
            "repo_id": spec.repo_id,
            "path": str(target),
        }


def _resolve_model(model: str) -> LocalModelSpec:
    key = DEFAULT_MODEL_KEY if model in {"", "default"} else model
    for spec in KNOWN_MODELS:
        if key in {spec.key, spec.repo_id, spec.directory_name}:
            return spec
    known = ", ".join(spec.key for spec in KNOWN_MODELS)
    raise ValueError(f"Unknown local model {model!r}. Known models: {known}")


def _snapshot_download(repo_id: str, local_dir: Path) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Local model download requires huggingface_hub. Install the semantic "
            'extra first: pip install "ai-policy-runtime[semantic]"'
        ) from exc

    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
    )


def check_sentence_transformer_model(model: str | Path) -> dict[str, Any]:
    """Check whether a local sentence-transformers model can be loaded."""

    model_name = str(model)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return {
            "usable": False,
            "error": "sentence-transformers is not installed in this Python environment.",
            "next_step": (
                "Run: ai-policy embedding configure --provider local --install, "
                'or install the semantic extra: pip install "ai-policy-runtime[semantic]"'
            ),
        }

    try:
        SentenceTransformer(model_name)
    except Exception as exc:
        return {
            "usable": False,
            "error": f"{type(exc).__name__}: {exc}",
            "next_step": (
                "Run: ai-policy embedding configure --provider local --install, "
                "or pass --model <existing sentence-transformers model path>."
            ),
        }

    return {
        "usable": True,
        "error": None,
        "next_step": None,
    }
