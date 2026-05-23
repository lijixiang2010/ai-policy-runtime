from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ai_policy_runtime.domain.config import EmbeddingConfig
from ai_policy_runtime.services.local_models import (
    LocalModelManager,
    check_sentence_transformer_model,
)
from ai_policy_runtime.task_analysis.analyzer import default_embedding_provider


def inspect_embedding_health(
    *,
    root: str | Path = ".",
    policy_root: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    include_env: bool = True,
    check_loadable: bool = True,
) -> dict[str, Any]:
    """Return the effective embedding configuration and local model health."""

    project_root = Path(root)
    config = config or {}
    provider = _effective_provider(config, include_env=include_env)
    base_url = _first_string(
        config.get("embeddingBaseUrl"),
        os.environ.get("AI_POLICY_EMBEDDING_BASE_URL") if include_env else None,
    )
    api_key_configured = bool(
        _first_string(
            config.get("embeddingApiKey"),
            os.environ.get("AI_POLICY_EMBEDDING_API_KEY") if include_env else None,
            os.environ.get("OPENAI_API_KEY") if include_env else None,
        )
    )
    model = _first_string(
        config.get("embeddingModel"),
        os.environ.get("AI_POLICY_EMBEDDING_MODEL") if include_env else None,
    )
    timeout = _first_string(
        config.get("embeddingTimeout"),
        os.environ.get("AI_POLICY_EMBEDDING_TIMEOUT") if include_env else None,
    )
    remote_configured = bool(base_url or api_key_configured)
    asset_root = _embedding_policy_root(project_root, policy_root, config)
    local_models = list(
        LocalModelManager(asset_root).inspect(check_loadable=check_loadable)
    )

    local_available: bool | None = None
    local_error: str | None = None
    next_step: str | None = None
    effective_model = model

    if provider == "local":
        if model:
            check = (
                check_sentence_transformer_model(_local_model_path(project_root, model))
                if check_loadable
                else {"usable": None, "error": None, "next_step": None}
            )
            local_available = check["usable"]
            local_error = check["error"]
            next_step = check["next_step"]
        else:
            usable_models = [item for item in local_models if item.get("usable")]
            local_available = bool(usable_models)
            if usable_models:
                effective_model = str(usable_models[0]["path"])
            elif local_models:
                first_model = local_models[0]
                local_error = _optional_string(first_model.get("error"))
                next_step = _optional_string(first_model.get("next_step"))
            else:
                next_step = _local_install_next_step()

    any_usable_local_model = any(item.get("usable") is True for item in local_models)
    ok = (
        remote_configured
        if provider == "openai-compatible"
        else local_available is True
        if provider == "local"
        else remote_configured or any_usable_local_model
    )
    if not ok and next_step is None:
        first_local_error = _first_local_value(local_models, "error")
        if local_error is None:
            local_error = first_local_error
        next_step = (
            _local_install_next_step()
            if provider == "local"
            else "Configure an OpenAI-compatible endpoint or run: "
            "ai-policy embedding configure --provider local --install"
        )

    return {
        "provider": provider,
        "base_url": base_url,
        "api_key_configured": api_key_configured,
        "model": effective_model,
        "timeout": timeout,
        "remote_configured": remote_configured,
        "local_available": local_available,
        "local_error": local_error,
        "next_step": None if ok else next_step,
        "local_models": local_models,
        "ok": ok,
    }


def test_embedding_provider(
    *,
    root: str | Path = ".",
    policy_root: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    include_env: bool = True,
    text: str = "AI Policy Runtime embedding health check",
) -> dict[str, Any]:
    """Run one embedding request against the effective provider."""

    health = inspect_embedding_health(
        root=root,
        policy_root=policy_root,
        config=config,
        include_env=include_env,
        check_loadable=True,
    )
    if not health["ok"]:
        return {
            **health,
            "probe_ok": False,
            "probe_error": health.get("next_step") or "Embedding provider is not configured.",
        }

    project_root = Path(root)
    asset_root = _embedding_policy_root(project_root, policy_root, config or {})
    embedding = _embedding_config(project_root, config or {}, include_env=include_env)
    try:
        provider = default_embedding_provider(asset_root, embedding)
        vectors = provider.encode([text])
        vector = vectors[0] if vectors else []
        if not vector:
            raise RuntimeError("Embedding provider returned an empty vector.")
    except Exception as exc:
        return {
            **health,
            "probe_ok": False,
            "probe_error": str(exc),
        }

    return {
        **health,
        "probe_ok": True,
        "probe_error": None,
        "vector_dimensions": len(vector),
        "provider_cache_key": str(getattr(provider, "model_name", provider.__class__.__name__)),
    }


def _effective_provider(config: Mapping[str, Any], *, include_env: bool) -> str:
    provider = _normalize_provider(config.get("embeddingProvider"))
    if provider:
        return provider
    if include_env:
        provider = _normalize_provider(os.environ.get("AI_POLICY_EMBEDDING_PROVIDER"))
        if provider:
            return provider
    return "auto"


def _embedding_policy_root(
    root: Path,
    policy_root: str | Path | None,
    config: Mapping[str, Any],
) -> Path:
    configured = policy_root or _optional_string(config.get("policyRoot"))
    if configured:
        path = Path(str(configured))
        return path if path.is_absolute() else root / path
    return root


def _local_model_path(root: Path, model: str) -> Path | str:
    path = Path(model)
    if path.is_absolute():
        return path
    return root / path


def _embedding_config(
    root: Path,
    config: Mapping[str, Any],
    *,
    include_env: bool,
) -> EmbeddingConfig | None:
    provider = _normalize_provider(config.get("embeddingProvider")) or None
    base_url = _first_string(
        config.get("embeddingBaseUrl"),
        os.environ.get("AI_POLICY_EMBEDDING_BASE_URL") if include_env else None,
    )
    api_key = _first_string(
        config.get("embeddingApiKey"),
        os.environ.get("AI_POLICY_EMBEDDING_API_KEY") if include_env else None,
        os.environ.get("OPENAI_API_KEY") if include_env else None,
    )
    model = _first_string(
        config.get("embeddingModel"),
        os.environ.get("AI_POLICY_EMBEDDING_MODEL") if include_env else None,
    )
    timeout = _optional_float(
        _first_string(
            config.get("embeddingTimeout"),
            os.environ.get("AI_POLICY_EMBEDDING_TIMEOUT") if include_env else None,
        )
    )
    if provider == "local" and model:
        model_path = _local_model_path(root, model)
        model = str(model_path)
    if not any(value is not None for value in (provider, base_url, api_key, model, timeout)):
        return None
    return EmbeddingConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout,
    )


def _normalize_provider(value: object) -> str:
    provider = _optional_string(value)
    if provider in {None, "auto"}:
        return ""
    return provider.strip().lower().replace("_", "-")


def _first_string(*values: object) -> str | None:
    for value in values:
        text = _optional_string(value)
        if text:
            return text
    return None


def _first_local_value(items: list[dict[str, Any]], key: str) -> str | None:
    for item in items:
        text = _optional_string(item.get(key))
        if text:
            return text
    return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    text = _optional_string(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _local_install_next_step() -> str:
    return (
        "Run: ai-policy embedding configure --provider local --install, "
        "or pass --model <existing sentence-transformers model path>."
    )
