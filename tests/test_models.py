from __future__ import annotations

from typing import Any

from notionchat.models import (
    cache_openai_models,
    get_cached_alias_map,
    get_cached_openai_models,
    list_openai_models_from_notion,
    normalize_request_model,
    parse_available_models,
    resolve_model,
)


def test_parse_available_models(mock_models_payload: dict[str, Any]):
    aliases = parse_available_models(mock_models_payload)
    assert aliases["claude-3.5-sonnet"] == "ambrosia-tart-high"
    assert aliases["claude-3.5-haiku"] == "ambrosia-tart-low"
    assert "gpt-4-disabled" not in aliases


def test_list_openai_models_from_notion(mock_models_payload: dict[str, Any]):
    models = list_openai_models_from_notion(
        mock_models_payload, default_notion_id="ambrosia-tart-high"
    )
    ids = [m["id"] for m in models]
    assert "claude-3.5-sonnet" in ids
    assert "claude-3.5-haiku" in ids
    assert "gpt-4-disabled" not in ids


def test_model_caching(mock_models_payload: dict[str, Any]):
    models = list_openai_models_from_notion(
        mock_models_payload, default_notion_id="ambrosia-tart-high"
    )
    aliases = parse_available_models(mock_models_payload)
    cache_openai_models(models, aliases)

    cached_models = get_cached_openai_models()
    assert cached_models is not None
    assert len(cached_models) == len(models)

    cached_aliases = get_cached_alias_map()
    assert cached_aliases == aliases


def test_resolve_model():
    aliases = {"claude-3.5-sonnet": "ambrosia-tart-high"}
    # Known alias
    assert (
        resolve_model("claude-3.5-sonnet", default="default-id", alias_map=aliases)
        == "ambrosia-tart-high"
    )
    # Fallback to default when None
    assert resolve_model(None, default="default-id", alias_map=aliases) == "default-id"
    # Pass-through for unknown model
    assert (
        resolve_model("unknown-model", default="default-id", alias_map=aliases) == "unknown-model"
    )


def test_normalize_request_model():
    assert normalize_request_model("notion-ai/claude-3.5-sonnet") == "claude-3.5-sonnet"
    assert normalize_request_model("gpt-4") == "gpt-4"
