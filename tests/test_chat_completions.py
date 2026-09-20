from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from notionchat.client import ChatResult


@pytest.mark.asyncio
async def test_healthz(app_client: AsyncClient):
    resp = await app_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_models_unauthorized(app_client: AsyncClient):
    resp = await app_client.get("/v1/models")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_models_authorized(app_client: AsyncClient):
    with patch(
        "notionchat.client.NotionAIClient.fetch_available_models", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = {
            "models": [
                {
                    "model": "ambrosia-tart-high",
                    "modelMessage": "claude-3.5-sonnet",
                    "isDisabled": False,
                }
            ]
        }
        resp = await app_client.get(
            "/v1/models",
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        assert data["data"][0]["id"] == "claude-3.5-sonnet"


@pytest.mark.asyncio
async def test_chat_completions_non_streaming(app_client: AsyncClient):
    mock_result = ChatResult(
        text="Paris is the capital of France.",
        thread_id="thread-test-123",
        input_tokens=15,
        output_tokens=8,
        model="claude-3.5-sonnet",
        tool_calls=[],
    )

    with (
        patch("notionchat.client.NotionAIClient.complete", new_callable=AsyncMock) as mock_complete,
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_fetch.return_value = {"models": []}
        mock_complete.return_value = mock_result

        payload = {
            "model": "claude-3.5-sonnet",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        }
        resp = await app_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["content"] == "Paris is the capital of France."
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["usage"]["total_tokens"] == 23


@pytest.mark.asyncio
async def test_chat_completions_streaming(app_client: AsyncClient):
    async def mock_deltas():
        yield "Hello"
        yield " world"

    mock_result = ChatResult(
        text="Hello world",
        thread_id="thread-test-456",
        input_tokens=5,
        output_tokens=3,
        model="claude-3.5-sonnet",
        tool_calls=[],
    )

    with (
        patch("notionchat.client.NotionAIClient.stream_deltas") as mock_stream,
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_fetch.return_value = {"models": []}
        mock_stream.return_value = (mock_deltas(), "thread-test-456", lambda: mock_result)

        payload = {
            "model": "claude-3.5-sonnet",
            "messages": [{"role": "user", "content": "Say hello world"}],
            "stream": True,
        }
        resp = await app_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "data: [DONE]" in body
        assert "Hello" in body
