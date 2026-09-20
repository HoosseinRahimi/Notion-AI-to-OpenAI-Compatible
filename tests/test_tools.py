from __future__ import annotations

from notionchat.tools import (
    extract_all_tool_calls_from_text,
    normalize_tools,
    prepare_chat_input,
)


def test_normalize_tools_standard_chat_format():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                },
            },
        }
    ]
    normalized = normalize_tools(tools)
    assert len(normalized) == 1
    assert normalized[0]["type"] == "function"
    assert normalized[0]["function"]["name"] == "get_weather"


def test_extract_tool_calls_from_prose():
    text = "Here is the command to run:\n```bash\npytest tests/\n```"
    calls = extract_all_tool_calls_from_text(text)
    assert isinstance(calls, list)


def test_prepare_chat_input_simple_user_message():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 2 + 2?"},
    ]
    system, prompt, tools_active, ide_agent, tools = prepare_chat_input(messages)
    assert "You are a helpful assistant." in (system or "")
    assert "What is 2 + 2?" in prompt
    assert not tools_active
    assert not ide_agent
