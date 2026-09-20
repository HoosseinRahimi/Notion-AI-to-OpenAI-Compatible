from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from notionchat.client import ChatResult
from notionchat.config import Settings
from notionchat.exceptions import NotionChatError
from notionchat.openai_api import create_app


@pytest.mark.asyncio
async def test_standard_streaming_no_replace_marker(test_settings: Settings):
    """Verify standard streaming emits append-only deltas without MUGHU_STREAM_REPLACE marker."""
    app = create_app(test_settings)
    headers = {"Authorization": f"Bearer {test_settings.api_key}"}
    transport = ASGITransport(app=app)

    async def mock_stream_deltas(*args: Any, **kwargs: Any):
        async def gen():
            # Deliberately include a replace mark from notion
            yield "Hello "
            yield "<<<MUGHU_STREAM_REPLACE>>>\nHello world!"

        return (
            gen(),
            "thread-123",
            lambda: ChatResult(text="Hello world!", thread_id="thread-123", model="gpt-4o"),
        )

    with (
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            new_callable=AsyncMock,
            return_value={"models": []},
        ),
        patch("notionchat.client.NotionAIClient.stream_deltas", side_effect=mock_stream_deltas),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            lines = resp.text.strip().split("\n\n")
            content_pieces = []
            for line in lines:
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                assert line.startswith("data: ")
                payload = json.loads(line[len("data: ") :])
                delta = payload["choices"][0]["delta"]
                if "content" in delta and delta["content"]:
                    content_pieces.append(delta["content"])

            full_content = "".join(content_pieces)
            # Ensure the marker was stripped/never exposed to standard OpenAI client
            assert "<<<MUGHU_STREAM_REPLACE>>>" not in full_content
            assert lines[-1] == "data: [DONE]"


@pytest.mark.asyncio
async def test_streaming_with_allow_replace_opt_in(test_settings: Settings):
    """Verify that with X-Allow-Stream-Replace header, replace marker is preserved."""
    app = create_app(test_settings)
    headers = {
        "Authorization": f"Bearer {test_settings.api_key}",
        "X-Allow-Stream-Replace": "1",
    }
    transport = ASGITransport(app=app)

    async def mock_stream_deltas(*args: Any, **kwargs: Any):
        assert kwargs.get("allow_stream_replace") is True

        async def gen():
            yield "Hello "
            yield "<<<MUGHU_STREAM_REPLACE>>>\nHello world!"

        return (
            gen(),
            "thread-123",
            lambda: ChatResult(text="Hello world!", thread_id="thread-123", model="gpt-4o"),
        )

    with (
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            new_callable=AsyncMock,
            return_value={"models": []},
        ),
        patch("notionchat.client.NotionAIClient.stream_deltas", side_effect=mock_stream_deltas),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            assert "<<<MUGHU_STREAM_REPLACE>>>" in resp.text


@pytest.mark.asyncio
async def test_streaming_authoritative_bridge_output(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    """When tools are active and no tool calls generated, result.text is the authoritative output."""
    monkeypatch.setenv("NOTIONCHAT_EXPERIMENTAL_TOOLS", "1")
    app = create_app(test_settings)
    headers = {"Authorization": f"Bearer {test_settings.api_key}"}
    transport = ASGITransport(app=app)

    # Simulate raw stream having a refusal/bad output, but bridge finalizing with cleaned result.text
    async def mock_stream_deltas(*args: Any, **kwargs: Any):
        async def gen():
            yield "I cannot execute tools."

        return (
            gen(),
            "thread-123",
            lambda: ChatResult(
                text="Authoritative answer after bridge retry",
                thread_id="thread-123",
                model="gpt-4o",
                tool_calls=None,
            ),
        )

    with (
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            new_callable=AsyncMock,
            return_value={"models": []},
        ),
        patch("notionchat.client.NotionAIClient.stream_deltas", side_effect=mock_stream_deltas),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                    "tools": [{"type": "function", "function": {"name": "test_fn"}}],
                    "stream": True,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            assert "Authoritative answer after bridge retry" in resp.text
            assert "I cannot execute tools." not in resp.text


@pytest.mark.asyncio
async def test_streaming_error_event_and_done(test_settings: Settings):
    """Verify stream error is emitted in OpenAI error format followed by data: [DONE]."""
    app = create_app(test_settings)
    headers = {"Authorization": f"Bearer {test_settings.api_key}"}
    transport = ASGITransport(app=app)

    async def mock_stream_deltas(*args: Any, **kwargs: Any):
        raise NotionChatError("Notion rate limited", status_code=429)

    with (
        patch(
            "notionchat.client.NotionAIClient.fetch_available_models",
            new_callable=AsyncMock,
            return_value={"models": []},
        ),
        patch("notionchat.client.NotionAIClient.stream_deltas", side_effect=mock_stream_deltas),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            lines = [line.strip() for line in resp.text.strip().split("\n\n") if line.strip()]
            assert len(lines) == 2
            # 1st event is the error payload
            err_data = json.loads(lines[0].removeprefix("data: "))
            assert "error" in err_data
            assert err_data["error"]["code"] == 429
            assert err_data["error"]["message"] == "Notion rate limited"
            # 2nd event is [DONE]
            assert lines[1] == "data: [DONE]"
