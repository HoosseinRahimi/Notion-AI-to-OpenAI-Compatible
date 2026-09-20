from __future__ import annotations

import json

from notionchat.ndjson import NDJSONStreamParser, clean_notion_output_text


def test_ndjson_text_delta_streaming():
    parser = NDJSONStreamParser()

    lines = [
        json.dumps(
            {
                "type": "patch",
                "v": [
                    {
                        "o": "a",
                        "p": "/s/-",
                        "v": {
                            "type": "assistant-reply",
                            "value": [{"type": "text", "content": "Hello world"}],
                        },
                    },
                    {"o": "a", "p": "/inputTokens", "v": 10},
                    {"o": "a", "p": "/outputTokens", "v": 5},
                ],
            }
        ),
    ]

    for line in lines:
        parser.feed_line(line)

    assert parser.text == "Hello world"
    assert parser.input_tokens == 10
    assert parser.output_tokens == 5


def test_ndjson_tool_use_streaming():
    parser = NDJSONStreamParser()

    lines = [
        json.dumps(
            {
                "type": "patch",
                "v": [
                    {
                        "o": "a",
                        "p": "/s/0/value/-",
                        "v": {
                            "type": "tool_use",
                            "id": "tool_123",
                            "name": "read_file",
                            "input": {"path": "main.py"},
                        },
                    }
                ],
            }
        ),
    ]

    for line in lines:
        parser.feed_line(line)

    tools = parser.tool_calls
    assert len(tools) == 1
    assert tools[0]["id"] == "tool_123"
    assert tools[0]["function"]["name"] == "read_file"
    assert json.loads(tools[0]["function"]["arguments"]) == {"path": "main.py"}


def test_clean_notion_output_text():
    raw = "Sure, I can help with that!\n\nHere is the answer: 42."
    cleaned = clean_notion_output_text(raw)
    assert "42" in cleaned
