from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from notionchat.client import ChatResult
from notionchat.config import Settings
from notionchat.exceptions import NotionChatError
from notionchat.models import cache_openai_models, clear_model_cache
from notionchat.openai_api import (
    POOL_THREAD_TTL_SECONDS,
    ChatCompletionRequest,
    _record_pooled_thread,
    _reuse_pool,
    _session_lock_key,
    _session_locks,
    _take_pooled_thread,
    create_app,
)


@pytest.fixture(autouse=True)
def _reset_state():
    _reuse_pool.clear()
    _session_locks.clear()
    clear_model_cache()
    yield
    _reuse_pool.clear()
    _session_locks.clear()
    clear_model_cache()


def _make_settings(tmp_path: Path, **kwargs: Any) -> Settings:
    defaults: dict[str, Any] = {
        "api_key": "test-key",
        "host": "127.0.0.1",
        "port": 1994,
        "account_path": tmp_path / "account.json",
        "thread_state_dir": tmp_path / "threads",
        "base_url": "https://app.notion.com/api/v3",
        "default_model": "gpt-4o",
        "thread_reuse_limit": 5,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def test_session_lock_key_differentiation(tmp_path: Path):
    settings = _make_settings(tmp_path, thread_reuse_limit=5)
    req_user1 = ChatCompletionRequest(messages=[], user="user-1")
    req_user2 = ChatCompletionRequest(messages=[], user="user-2")
    req_pool1 = ChatCompletionRequest(messages=[], model="openai/gpt-4o")
    req_pool2 = ChatCompletionRequest(messages=[], model="claude-3-5-sonnet")

    assert _session_lock_key(req_user1, settings) == "user:user-1"
    assert _session_lock_key(req_user2, settings) == "user:user-2"
    assert _session_lock_key(req_pool1, settings).startswith("pool:")
    assert _session_lock_key(req_pool2, settings).startswith("pool:")
    assert _session_lock_key(req_pool1, settings) != _session_lock_key(req_pool2, settings)

    # When thread reuse is disabled, requests get ephemeral unique keys
    settings_no_reuse = _make_settings(tmp_path, thread_reuse_limit=0)
    req_ephem1 = ChatCompletionRequest(messages=[])
    req_ephem2 = ChatCompletionRequest(messages=[])
    assert _session_lock_key(req_ephem1, settings_no_reuse).startswith("ephemeral:")
    assert _session_lock_key(req_ephem1, settings_no_reuse) != _session_lock_key(
        req_ephem2, settings_no_reuse
    )


def test_pooled_thread_ttl_expiry(tmp_path: Path):
    settings = _make_settings(tmp_path, thread_reuse_limit=5)
    req = ChatCompletionRequest(messages=[], model="openai/gpt-4o")

    # Record a thread
    _record_pooled_thread(req, "thread-123", settings)
    assert _take_pooled_thread(req, settings) == "thread-123"

    # Simulate TTL expiration
    slot = list(_reuse_pool.values())[0]
    slot["created_at"] = time.time() - POOL_THREAD_TTL_SECONDS - 10

    # Should expire and return None
    assert _take_pooled_thread(req, settings) is None
    # Pool should now be empty for that model
    assert len(_reuse_pool) == 0


def test_pooled_thread_reuse_limit(tmp_path: Path):
    settings = _make_settings(tmp_path, thread_reuse_limit=2)
    req = ChatCompletionRequest(messages=[], model="openai/gpt-4o")

    _record_pooled_thread(req, "thread-abc", settings)

    # 1st reuse
    assert _take_pooled_thread(req, settings) == "thread-abc"
    _record_pooled_thread(req, "thread-abc", settings)

    # 2nd reuse (limit reached)
    assert _take_pooled_thread(req, settings) is None


@pytest.mark.asyncio
async def test_readyz_endpoint(tmp_path: Path):
    settings = _make_settings(tmp_path)
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without account loaded and invalid env, readyz returns 503
        with patch(
            "notionchat.openai_api.load_account_from_env", side_effect=Exception("No token")
        ):
            resp = await client.get("/readyz")
            assert resp.status_code == 503
            assert "Notion credentials not ready" in resp.json()["detail"]

        # With account loaded in app.state, readyz returns 200
        app.state.account = "mock_account"
        resp = await client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_models_stale_cache_fallback(tmp_path: Path):
    settings = _make_settings(tmp_path)
    app = create_app(settings)
    app.state.account = "mock_account"
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case 1: Notion fails and NO cache exists -> 502 Bad Gateway
        with patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            side_effect=NotionChatError("Upstream timeout", status_code=504),
        ):
            resp = await client.get("/v1/models", headers=headers)
            assert resp.status_code == 502
            assert "Failed to fetch models from upstream" in resp.json()["detail"]

        # Case 2: Stale cache exists (e.g. from earlier fetch) -> returns stale cache with 200
        stale_data = [{"id": "cached-model", "object": "model"}]
        cache_openai_models(stale_data, [])
        # Manually expire the live cache by backdating timestamp
        import notionchat.models as m

        if m._models_cache is not None:
            _, models, alias_map = m._models_cache
            m._models_cache = (time.time() - 400.0, models, alias_map)

        with patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            side_effect=NotionChatError("Upstream timeout", status_code=504),
        ):
            resp = await client.get("/v1/models", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["object"] == "list"
            assert data["data"][0]["id"] == "cached-model"


@pytest.mark.asyncio
async def test_concurrent_requests_same_session_serialized(test_settings: Settings):
    """Verify concurrent requests for the same user session do not overlap execution."""
    app = create_app(test_settings)
    headers = {"Authorization": f"Bearer {test_settings.api_key}"}
    transport = ASGITransport(app=app)

    active_executions = 0
    max_concurrent_for_session = 0

    async def mock_complete(*args: Any, **kwargs: Any):
        nonlocal active_executions, max_concurrent_for_session
        active_executions += 1
        max_concurrent_for_session = max(max_concurrent_for_session, active_executions)
        await asyncio.sleep(0.05)
        active_executions -= 1
        return ChatResult(text="Hello", thread_id="t1", model="m1")

    with (
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            new_callable=AsyncMock,
            return_value={"models": []},
        ),
        patch("notionchat.client.NotionAIClient.complete", side_effect=mock_complete),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 3 requests for SAME user
            payload = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "user": "session-1",
            }
            results = await asyncio.gather(
                client.post("/v1/chat/completions", json=payload, headers=headers),
                client.post("/v1/chat/completions", json=payload, headers=headers),
                client.post("/v1/chat/completions", json=payload, headers=headers),
            )
            assert all(r.status_code == 200 for r in results)
            # Serialization guarantees max_concurrent_for_session == 1
            assert max_concurrent_for_session == 1


@pytest.mark.asyncio
async def test_concurrent_requests_different_sessions_parallel(test_settings: Settings):
    """Verify concurrent requests for different sessions run in parallel."""
    app = create_app(test_settings)
    headers = {"Authorization": f"Bearer {test_settings.api_key}"}
    transport = ASGITransport(app=app)

    active_executions = 0
    max_concurrent = 0

    async def mock_complete(*args: Any, **kwargs: Any):
        nonlocal active_executions, max_concurrent
        active_executions += 1
        max_concurrent = max(max_concurrent, active_executions)
        await asyncio.sleep(0.05)
        active_executions -= 1
        return ChatResult(text="Hello", thread_id="t1", model="m1")

    with (
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            new_callable=AsyncMock,
            return_value={"models": []},
        ),
        patch("notionchat.client.NotionAIClient.complete", side_effect=mock_complete),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 3 requests for DIFFERENT users
            results = await asyncio.gather(
                client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": "hi"}],
                        "user": "user-A",
                    },
                    headers=headers,
                ),
                client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": "hi"}],
                        "user": "user-B",
                    },
                    headers=headers,
                ),
                client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": "hi"}],
                        "user": "user-C",
                    },
                    headers=headers,
                ),
            )
            assert all(r.status_code == 200 for r in results)
            # Parallel execution allows > 1 concurrent executions
            assert max_concurrent > 1
