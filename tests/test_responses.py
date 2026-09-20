from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from notionchat.client import ChatResult


@pytest.mark.asyncio
async def test_responses_string_input(app_client: AsyncClient):
    mock_result = ChatResult(
        text="Quantum computing uses qubits.",
        thread_id="thread-resp-1",
        input_tokens=10,
        output_tokens=6,
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
            "input": "Explain quantum computing",
        }
        resp = await app_client.post(
            "/v1/responses",
            json=payload,
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "response"
        assert data["status"] == "completed"
        assert len(data["output"]) >= 1
        assert data["output"][0]["type"] == "message"
        assert data["output"][0]["content"][0]["text"] == "Quantum computing uses qubits."
        assert data["usage"]["total_tokens"] == 16


@pytest.mark.asyncio
async def test_responses_input_text_block(app_client: AsyncClient):
    mock_result = ChatResult(
        text="Hello! How can I help you?",
        thread_id="thread-resp-2",
        input_tokens=5,
        output_tokens=7,
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
            "input": [{"type": "input_text", "text": "hello"}],
        }
        resp = await app_client.post(
            "/v1/responses",
            json=payload,
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["output"][0]["content"][0]["text"] == "Hello! How can I help you?"


@pytest.mark.asyncio
async def test_responses_flat_tools(app_client: AsyncClient):
    mock_result = ChatResult(
        text=None,
        thread_id="thread-resp-3",
        input_tokens=20,
        output_tokens=15,
        model="claude-3.5-sonnet",
        tool_calls=[
            {
                "id": "call_weather_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location": "Tokyo"}'},
            }
        ],
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
            "input": "What is the weather in Tokyo?",
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
        }
        resp = await app_client.post(
            "/v1/responses",
            json=payload,
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert len(data["output"]) == 1
        tool_item = data["output"][0]
        assert tool_item["type"] == "function_call"
        assert tool_item["name"] == "get_weather"
        assert tool_item["arguments"] == '{"location": "Tokyo"}'
        assert tool_item["status"] == "completed"


@pytest.mark.asyncio
async def test_responses_function_call_output(app_client: AsyncClient):
    mock_result = ChatResult(
        text="The weather in Tokyo is sunny and 22°C.",
        thread_id="thread-resp-4",
        input_tokens=30,
        output_tokens=10,
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
            "input": [
                {
                    "type": "function_call",
                    "call_id": "call_weather_1",
                    "name": "get_weather",
                    "arguments": '{"location": "Tokyo"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_weather_1",
                    "output": '{"temperature": 22, "condition": "sunny"}',
                },
            ],
        }
        resp = await app_client.post(
            "/v1/responses",
            json=payload,
            headers={"Authorization": "Bearer sk-test-key-12345"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["output"][0]["content"][0]["text"] == "The weather in Tokyo is sunny and 22°C."


@pytest.mark.asyncio
async def test_responses_rejected_parameters(app_client: AsyncClient):
    # previous_response_id rejected with 400
    resp = await app_client.post(
        "/v1/responses",
        json={"model": "claude-3.5-sonnet", "input": "hi", "previous_response_id": "resp_old"},
        headers={"Authorization": "Bearer sk-test-key-12345"},
    )
    assert resp.status_code == 400
    assert "previous_response_id" in resp.json()["detail"]

    # stream=True rejected with 400
    resp2 = await app_client.post(
        "/v1/responses",
        json={"model": "claude-3.5-sonnet", "input": "hi", "stream": True},
        headers={"Authorization": "Bearer sk-test-key-12345"},
    )
    assert resp2.status_code == 400
    assert "Streaming is not yet supported" in resp2.json()["detail"]
