from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from notionchat.client import ChatResult, NotionAIClient
from notionchat.config import (
    Settings,
    load_account_from_env,
    load_settings,
    validate_settings_security,
)
from notionchat.exceptions import NotionChatError
from notionchat.models import (
    cache_openai_models,
    get_cached_alias_map,
    get_cached_openai_models,
    get_stale_cached_openai_models,
    list_openai_models_from_notion,
    normalize_request_model,
    parse_available_models,
    resolve_model,
)
from notionchat.tools import (
    bridge_ide_agent_response,
    build_tool_denial_retry_append,
    client_tool_names,
    is_ide_agent_messages,
    looks_like_coding_task_prompt,
    looks_like_tool_denial,
    normalize_tools,
    prepare_chat_input,
)

log = logging.getLogger(__name__)

_session_threads: dict[str, str] = {}
_session_models: dict[str, str] = {}
_reuse_pool: dict[str, dict[str, Any]] = {}


class FunctionDetails(BaseModel):
    name: str
    arguments: str = "{}"


class ToolCallPart(BaseModel):
    id: str
    type: str = "function"
    function: FunctionDetails


class ToolFunctionSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "function"
    function: ToolFunctionSchema


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCallPart] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "notion-ai"
    messages: list[ChatMessage]
    stream: bool = False
    user: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[Any] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = True


# --- OpenAI Responses API (POST /v1/responses) ---
# Issue #4: Claude Code (via 9router) hits /v1/responses and gets 404.
# We accept the Responses API shape, delegate to the existing
# chat_completions pipeline, then re-shape the response so clients that
# expect the newer API (Codex, Claude Code, etc.) get a valid payload.


class ResponsesInputMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str | None = None
    type: str | None = None
    content: str | list[Any] | None = None
    text: str | None = None
    call_id: str | None = None
    output: Any | None = None
    name: str | None = None
    arguments: Any | None = None


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    input: str | list[Any] | None = None
    messages: list[ChatMessage] | None = None
    instructions: str | None = None
    stream: bool = False
    tools: list[Any] | None = None
    tool_choice: Any | None = None
    previous_response_id: str | None = None
    max_output_tokens: int | None = None
    store: bool | None = None
    parallel_tool_calls: bool | None = None
    temperature: float | None = None
    user: str | None = None


def _responses_to_chat(req: ResponsesRequest) -> ChatCompletionRequest:
    """Translate a Responses API request into a ChatCompletionRequest."""
    chat_messages: list[ChatMessage] = []

    if req.instructions:
        chat_messages.append(ChatMessage(role="system", content=req.instructions))

    raw_input = req.input
    if isinstance(raw_input, str):
        if raw_input:
            chat_messages.append(ChatMessage(role="user", content=raw_input))
    elif isinstance(raw_input, list):
        for item in raw_input:
            if isinstance(item, str):
                chat_messages.append(ChatMessage(role="user", content=item))
                continue

            item_dict: dict[str, Any] = (
                item.model_dump()
                if hasattr(item, "model_dump")
                else (item if isinstance(item, dict) else {})
            )
            item_type = item_dict.get("type")

            if item_type == "input_text":
                text = item_dict.get("text", "")
                chat_messages.append(ChatMessage(role="user", content=text))
            elif item_type == "output_text":
                text = item_dict.get("text", "")
                chat_messages.append(ChatMessage(role="assistant", content=text))
            elif item_type == "function_call":
                call_id = (
                    item_dict.get("call_id")
                    or item_dict.get("id")
                    or f"call_{uuid.uuid4().hex[:24]}"
                )
                name = item_dict.get("name", "")
                args = item_dict.get("arguments", "{}")
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                chat_messages.append(
                    ChatMessage(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            ToolCallPart(
                                id=call_id,
                                type="function",
                                function=FunctionDetails(name=name, arguments=str(args)),
                            )
                        ],
                    )
                )
            elif item_type == "function_call_output":
                call_id = item_dict.get("call_id") or item_dict.get("id")
                output = item_dict.get("output", "")
                if isinstance(output, (dict, list)):
                    output = json.dumps(output, ensure_ascii=False)
                chat_messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=call_id,
                        content=str(output),
                    )
                )
            elif item_type == "message" or "role" in item_dict:
                role = item_dict.get("role") or "user"
                raw_content = item_dict.get("content")
                if isinstance(raw_content, list):
                    parts: list[str] = []
                    for part in raw_content:
                        if isinstance(part, str):
                            parts.append(part)
                        elif isinstance(part, dict) and "text" in part:
                            parts.append(str(part["text"]))
                    content_str = "".join(parts)
                    chat_messages.append(ChatMessage(role=role, content=content_str))
                else:
                    chat_messages.append(ChatMessage(role=role, content=raw_content))

    has_user_msg = any(m.role in ("user", "tool") for m in chat_messages)
    if not has_user_msg and req.messages:
        chat_messages.extend(req.messages)

    chat_tools: list[Any] = []
    if req.tools:
        for t in req.tools:
            t_dict = (
                t.model_dump() if hasattr(t, "model_dump") else (t if isinstance(t, dict) else {})
            )
            if t_dict.get("type") == "function" and "function" not in t_dict and "name" in t_dict:
                chat_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t_dict["name"],
                            "description": t_dict.get("description"),
                            "parameters": t_dict.get("parameters"),
                        },
                    }
                )
            else:
                chat_tools.append(t_dict)

    return ChatCompletionRequest(
        model=req.model,
        messages=chat_messages,
        stream=False,
        tools=chat_tools or None,
        tool_choice=req.tool_choice,
        temperature=req.temperature,
        user=req.user,
    )


def _chat_to_responses(chat_resp: dict[str, Any], model: str) -> dict[str, Any]:
    """Re-shape a Chat Completions response into the Responses API shape."""
    choices = chat_resp.get("choices") or []
    output: list[dict[str, Any]] = []
    if choices:
        first = choices[0]
        message = first.get("message") or {}
        text = message.get("content")
        if text:
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{uuid.uuid4().hex[:24]}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                            "annotations": [],
                        }
                    ],
                }
            )
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:24]}"
            output.append(
                {
                    "type": "function_call",
                    "id": call_id,
                    "call_id": call_id,
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", "{}"),
                    "status": "completed",
                }
            )

    if not output:
        output.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex[:24]}",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "",
                        "annotations": [],
                    }
                ],
            }
        )

    usage = chat_resp.get("usage") or {}
    resp_id = chat_resp.get("id") or f"resp_{uuid.uuid4().hex[:24]}"
    if resp_id.startswith("chatcmpl-"):
        resp_id = "resp_" + resp_id[len("chatcmpl-") :]

    return {
        "id": resp_id,
        "object": "response",
        "created_at": chat_resp.get("created") or int(time.time()),
        "status": "completed",
        "model": model,
        "output": output,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def _tools_payload(req: ChatCompletionRequest) -> list[dict[str, Any]]:
    if not req.tools:
        return []
    out: list[dict[str, Any]] = []
    for item in req.tools:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, ToolDefinition) or hasattr(item, "model_dump"):
            out.append(item.model_dump())
    return out


def _resolved_request_model(req: ChatCompletionRequest, settings: Settings) -> str:
    return resolve_model(
        normalize_request_model(req.model) or settings.default_model,
        default=settings.default_model,
        alias_map=get_cached_alias_map(),
    )


def _resolve_thread_id(req: ChatCompletionRequest, settings: Settings) -> str | None:
    if not req.user:
        return None

    resolved = _resolved_request_model(req, settings)
    previous = _session_models.get(req.user)
    if previous and previous != resolved:
        log.info(
            "Session %r model changed %r -> %r — dropping Notion thread",
            req.user,
            previous,
            resolved,
        )
        _session_threads.pop(req.user, None)
    _session_models[req.user] = resolved

    return _session_threads.get(req.user)


def _remember_thread(req: ChatCompletionRequest, thread_id: str, settings: Settings) -> None:
    if req.user:
        _session_threads[req.user] = thread_id
        _session_models[req.user] = _resolved_request_model(req, settings)


POOL_THREAD_TTL_SECONDS = 3600.0  # 1 hour
MAX_REUSE_POOL_SIZE = 50

_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()


async def _get_session_lock(session_key: str) -> asyncio.Lock:
    async with _session_locks_guard:
        if session_key not in _session_locks:
            _session_locks[session_key] = asyncio.Lock()
        return _session_locks[session_key]


def _session_lock_key(req: ChatCompletionRequest, settings: Settings) -> str:
    if req.user:
        return f"user:{req.user}"
    if settings.thread_reuse_limit > 0:
        return f"pool:{_resolved_request_model(req, settings)}"
    return f"ephemeral:{uuid.uuid4().hex}"


def _take_pooled_thread(req: ChatCompletionRequest, settings: Settings) -> str | None:
    """Reuse a shared Notion thread for up to thread_reuse_limit completions within TTL."""
    limit = settings.thread_reuse_limit
    if limit <= 0:
        return None
    model = _resolved_request_model(req, settings)
    slot = _reuse_pool.get(model)
    if not slot:
        return None
    created_at = float(slot.get("created_at") or 0)
    now = time.time()
    if now - created_at > POOL_THREAD_TTL_SECONDS:
        log.info(
            "Pooled thread for model %r expired (TTL=%ss) — opening new Notion chat",
            model,
            POOL_THREAD_TTL_SECONDS,
        )
        _reuse_pool.pop(model, None)
        return None
    thread_id = slot.get("thread_id")
    uses = int(slot.get("uses") or 0)
    if not isinstance(thread_id, str) or not thread_id:
        return None
    if uses >= limit:
        log.info(
            "Thread reuse limit reached (%d/%d) for model %r — opening new Notion chat",
            uses,
            limit,
            model,
        )
        _reuse_pool.pop(model, None)
        return None
    log.info(
        "Reusing Notion thread %s (%d/%d) model=%r",
        thread_id[:8],
        uses + 1,
        limit,
        model,
    )
    return thread_id


def _record_pooled_thread(req: ChatCompletionRequest, thread_id: str, settings: Settings) -> None:
    limit = settings.thread_reuse_limit
    if limit <= 0 or not thread_id:
        return
    model = _resolved_request_model(req, settings)
    now = time.time()
    slot = _reuse_pool.get(model)
    if slot and slot.get("thread_id") == thread_id:
        slot["uses"] = int(slot.get("uses") or 0) + 1
    else:
        if len(_reuse_pool) >= MAX_REUSE_POOL_SIZE:
            oldest_key = min(
                _reuse_pool.keys(), key=lambda k: float(_reuse_pool[k].get("created_at", 0))
            )
            _reuse_pool.pop(oldest_key, None)
        _reuse_pool[model] = {"thread_id": thread_id, "uses": 1, "created_at": now}
        log.info(
            "Started reusable Notion thread %s (1/%d) model=%r",
            thread_id[:8],
            limit,
            model,
        )


def _resolve_request_thread(
    req: ChatCompletionRequest,
    settings: Settings,
    *,
    ide_agent: bool,
    tools_active: bool,
) -> str | None:
    # Prefer explicit OpenAI `user` session continuity for normal chat.
    if not ide_agent and not tools_active:
        thread_id = _resolve_thread_id(req, settings)
        if thread_id:
            return thread_id
    return _take_pooled_thread(req, settings)


def _remember_request_thread(
    req: ChatCompletionRequest,
    thread_id: str,
    settings: Settings,
    *,
    ide_agent: bool,
    tools_active: bool,
) -> None:
    if not ide_agent and not tools_active:
        _remember_thread(req, thread_id, settings)
    # Shared pool is only for requests without an OpenAI `user` session key.
    if not req.user:
        _record_pooled_thread(req, thread_id, settings)


async def _ensure_model_aliases(client: NotionAIClient, settings: Settings) -> None:
    if get_cached_alias_map() is not None:
        return
    try:
        raw = await client.fetch_available_models()
        data = list_openai_models_from_notion(
            raw,
            default_notion_id=settings.default_model,
        )
        cache_openai_models(data, parse_available_models(raw))
    except NotionChatError as e:
        log.warning("Could not prefetch Notion model aliases: %s", e)


def _assistant_message(result: ChatResult) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant"}
    if result.tool_calls:
        msg["content"] = result.text
        msg["tool_calls"] = result.tool_calls
    else:
        msg["content"] = result.text or ""
    return msg


def _usage(result: ChatResult) -> dict[str, int]:
    return {
        "prompt_tokens": result.input_tokens,
        "completion_tokens": result.output_tokens,
        "total_tokens": result.input_tokens + result.output_tokens,
    }


def _chunk(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _bridge_ide_agent(
    result: ChatResult,
    *,
    req: ChatCompletionRequest,
    tools: list[dict[str, Any]],
    prompt: str,
    ide_agent: bool,
    tools_active: bool,
) -> ChatResult:
    if not ide_agent or not tools_active:
        return result
    text, tool_calls = bridge_ide_agent_response(
        messages=req.messages,
        notion_text=result.text,
        notion_tool_calls=result.tool_calls,
        client_tools=tools,
        prompt=prompt,
    )
    if tool_calls:
        log.info(
            "IDE bridge tool_calls=%s (notion text_len=%s)",
            [(tc.get("function") or {}).get("name") for tc in tool_calls],
            len(result.text or ""),
        )
        return ChatResult(
            text=text,
            thread_id=result.thread_id,
            model=result.model,
            tool_calls=tool_calls,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    if looks_like_tool_denial(result.text):
        log.info("IDE bridge suppressed Notion tool denial (text_len=%s)", len(result.text or ""))
        return ChatResult(
            text=None,
            thread_id=result.thread_id,
            model=result.model,
            tool_calls=None,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    return ChatResult(
        text=text if text is not None else result.text,
        thread_id=result.thread_id,
        model=result.model,
        tool_calls=None,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


async def _bridge_ide_agent_async(
    client: NotionAIClient,
    result: ChatResult,
    *,
    req: ChatCompletionRequest,
    tools: list[dict[str, Any]],
    prompt: str,
    system: str | None,
    ide_agent: bool,
    tools_active: bool,
) -> ChatResult:
    bridged = _bridge_ide_agent(
        result,
        req=req,
        tools=tools,
        prompt=prompt,
        ide_agent=ide_agent,
        tools_active=tools_active,
    )
    if bridged.tool_calls or not ide_agent or not tools_active:
        return bridged

    should_retry = looks_like_tool_denial(result.text) or looks_like_coding_task_prompt(prompt)
    if not should_retry:
        return bridged

    log.info(
        "IDE bridge retry: no tool_calls after compile (denial=%s)",
        looks_like_tool_denial(result.text),
    )
    retry_system = (system or "").strip()
    append = build_tool_denial_retry_append()
    retry_system = f"{retry_system}\n\n{append}".strip() if retry_system else append
    retry = await client.complete(
        prompt=prompt,
        system=retry_system,
        model=req.model,
        thread_id=None,
        tools_active=tools_active,
        ide_agent_mode=ide_agent,
        client_tools=tools,
    )
    return _bridge_ide_agent(
        retry,
        req=req,
        tools=tools,
        prompt=prompt,
        ide_agent=ide_agent,
        tools_active=tools_active,
    )


async def _stream_openai(
    client: NotionAIClient,
    req: ChatCompletionRequest,
    system: str | None,
    prompt: str,
    thread_id: str | None,
    settings: Settings,
    *,
    tools: list[dict[str, Any]],
    tools_active: bool,
    ide_agent: bool,
    content_mode: bool = False,
    allow_stream_replace: bool = False,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    try:
        session_lock = await _get_session_lock(_session_lock_key(req, settings))
        async with session_lock:
            try:
                deltas, active_thread_id, finalize = await client.stream_deltas(
                    prompt=prompt,
                    system=system,
                    model=req.model,
                    thread_id=thread_id,
                    tools_active=tools_active,
                    ide_agent_mode=ide_agent,
                    client_tools=tools,
                    buffer_until_complete=False,
                    allow_stream_replace=allow_stream_replace,
                )

                if tools_active:
                    buffered: list[str] = []
                    async for piece in deltas:
                        buffered.append(piece)
                    try:
                        result = finalize()
                    except NotionChatError:
                        empty = ChatResult(
                            text=None,
                            thread_id=active_thread_id,
                            model=req.model,
                            tool_calls=None,
                        )
                        result = await _bridge_ide_agent_async(
                            client,
                            empty,
                            req=req,
                            tools=tools,
                            prompt=prompt,
                            system=system,
                            ide_agent=ide_agent,
                            tools_active=tools_active,
                        )
                        if not result.tool_calls and not (result.text or "").strip():
                            raise
                    else:
                        result = await _bridge_ide_agent_async(
                            client,
                            result,
                            req=req,
                            tools=tools,
                            prompt=prompt,
                            system=system,
                            ide_agent=ide_agent,
                            tools_active=tools_active,
                        )
                    _remember_request_thread(
                        req,
                        result.thread_id,
                        settings,
                        ide_agent=ide_agent,
                        tools_active=tools_active,
                    )

                    if result.tool_calls:
                        yield _chunk(
                            completion_id=completion_id,
                            created=created,
                            model=req.model,
                            delta={"role": "assistant", "content": None},
                        )
                        for index, tc in enumerate(result.tool_calls):
                            fn = tc.get("function") or {}
                            yield _chunk(
                                completion_id=completion_id,
                                created=created,
                                model=req.model,
                                delta={
                                    "tool_calls": [
                                        {
                                            "index": index,
                                            "id": tc.get("id"),
                                            "type": "function",
                                            "function": {
                                                "name": fn.get("name", ""),
                                                "arguments": "",
                                            },
                                        }
                                    ]
                                },
                            )
                            args = str(fn.get("arguments", ""))
                            step = max(1, len(args) // 4)
                            for pos in range(0, len(args), step):
                                yield _chunk(
                                    completion_id=completion_id,
                                    created=created,
                                    model=req.model,
                                    delta={
                                        "tool_calls": [
                                            {
                                                "index": index,
                                                "function": {"arguments": args[pos : pos + step]},
                                            }
                                        ]
                                    },
                                )
                        yield _chunk(
                            completion_id=completion_id,
                            created=created,
                            model=req.model,
                            delta={},
                            finish_reason="tool_calls",
                        )
                    else:
                        # Authoritative bridge output: prefer result.text
                        text_to_emit = result.text or "".join(buffered)
                        if text_to_emit:
                            yield _chunk(
                                completion_id=completion_id,
                                created=created,
                                model=req.model,
                                delta={"content": text_to_emit},
                            )
                        yield _chunk(
                            completion_id=completion_id,
                            created=created,
                            model=req.model,
                            delta={},
                            finish_reason="stop",
                        )
                else:
                    # Live-stream deltas. Notion may rewrite earlier blocks; client.py emits
                    # <<<MUGHU_STREAM_REPLACE>>> snapshots for those — keep streaming.
                    live_parts: list[str] = []
                    replace_mark = "<<<MUGHU_STREAM_REPLACE>>>\n"
                    async for piece in deltas:
                        if not allow_stream_replace and replace_mark in piece:
                            piece = piece.replace(replace_mark, "")
                        if piece:
                            live_parts.append(piece)
                            yield _chunk(
                                completion_id=completion_id,
                                created=created,
                                model=req.model,
                                delta={"content": piece},
                            )
                    result = finalize()
                    _remember_request_thread(
                        req,
                        result.thread_id,
                        settings,
                        ide_agent=ide_agent,
                        tools_active=tools_active,
                    )

                    # Final authoritative snapshot if live stream drifted from cleaned result.
                    final_text = (result.text or "").strip()
                    live_joined = "".join(live_parts)
                    live_text = (
                        live_joined[live_joined.rfind(replace_mark) + len(replace_mark) :]
                        if replace_mark in live_joined
                        else live_joined
                    ).strip()
                    if (
                        allow_stream_replace
                        and final_text
                        and content_mode
                        and (
                            len(final_text) > len(live_text) + 40
                            or (
                                live_text
                                and final_text != live_text
                                and not final_text.startswith(live_text[: min(200, len(live_text))])
                            )
                        )
                    ):
                        replace_payload = f"{replace_mark}{final_text}"
                        step = 600
                        for pos in range(0, len(replace_payload), step):
                            yield _chunk(
                                completion_id=completion_id,
                                created=created,
                                model=req.model,
                                delta={"content": replace_payload[pos : pos + step]},
                            )
                    elif not allow_stream_replace and final_text and not live_parts:
                        yield _chunk(
                            completion_id=completion_id,
                            created=created,
                            model=req.model,
                            delta={"content": final_text},
                        )

                    finish_reason = "tool_calls" if result.tool_calls else "stop"
                    if result.tool_calls:
                        yield _chunk(
                            completion_id=completion_id,
                            created=created,
                            model=req.model,
                            delta={"role": "assistant", "tool_calls": result.tool_calls},
                        )
                    yield _chunk(
                        completion_id=completion_id,
                        created=created,
                        model=req.model,
                        delta={},
                        finish_reason=finish_reason,
                    )

                yield "data: [DONE]\n\n"
            except NotionChatError as e:
                err_type = "notion_error" if e.status_code >= 500 else "invalid_request_error"
                err = {
                    "error": {
                        "message": str(e),
                        "type": err_type,
                        "code": e.status_code,
                    }
                }
                yield f"data: {json.dumps(err)}\n\n"
                yield "data: [DONE]\n\n"
    finally:
        await client.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        # Save the original exception handler if set
        original_handler = loop.get_exception_handler()

        def win_fatal_loop_exception_handler(loop, context):
            exception = context.get("exception")
            message = context.get("message", "")

            is_fatal = False
            if exception:
                winerr = getattr(exception, "winerror", None)
                if winerr in (121, 10053, 10054):
                    is_fatal = True
                else:
                    err_msg = str(exception)
                    if any(
                        code in err_msg
                        for code in ("[WinError 121]", "[WinError 10054]", "[WinError 10053]")
                    ) or isinstance(exception, (ConnectionResetError, ConnectionAbortedError)):
                        is_fatal = True
            elif "event loop self pipe" in message or "SelectorThread" in message:
                is_fatal = True

            if is_fatal:
                log.critical(
                    "Fatal Windows event loop socket/pipe error detected (caused by PC waking up from hibernation/sleep). "
                    "The event loop has been corrupted and cannot recover. Terminating process immediately to prevent hang... "
                    "Exception: %s, Message: %s",
                    exception,
                    message,
                )
                os._exit(1)

            if original_handler:
                original_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        loop.set_exception_handler(win_fatal_loop_exception_handler)

    settings = getattr(app.state, "settings", None)
    if settings is not None:
        try:
            account = load_account_from_env(settings)
            app.state.account = account
            settings.thread_state_dir.mkdir(parents=True, exist_ok=True)
            client = NotionAIClient(
                account,
                base_url=settings.base_url,
                thread_state_dir=settings.thread_state_dir,
            )
            try:
                raw = await client.fetch_available_models()
                data = list_openai_models_from_notion(
                    raw,
                    default_notion_id=settings.default_model,
                )
                cache_openai_models(data, parse_available_models(raw))
                log.info("Prefetched %d Notion model aliases on startup", len(data))
            finally:
                await client.aclose()
        except Exception as e:
            log.warning("Could not prefetch Notion models on startup: %s", e)

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    validate_settings_security(settings)
    app = FastAPI(title="NotionChat", version="0.4.0", lifespan=lifespan)
    app.state.settings = settings

    def verify_key(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(token, settings.api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")

    def get_client() -> NotionAIClient:
        account = getattr(app.state, "account", None)
        if account is None:
            account = load_account_from_env(settings)
            app.state.account = account
        settings.thread_state_dir.mkdir(parents=True, exist_ok=True)
        return NotionAIClient(
            account,
            base_url=settings.base_url,
            thread_state_dir=settings.thread_state_dir,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        account = getattr(app.state, "account", None)
        if account is None:
            try:
                account = load_account_from_env(settings)
                app.state.account = account
            except Exception as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"Notion credentials not ready: {e}",
                ) from e
        return {"status": "ready"}

    @app.get("/v1/models")
    async def list_models(_: None = Depends(verify_key)) -> dict[str, Any]:
        cached = get_cached_openai_models()
        if cached is not None:
            return {"object": "list", "data": cached}

        client = get_client()
        try:
            raw = await client.fetch_available_models()
            data = list_openai_models_from_notion(
                raw,
                default_notion_id=settings.default_model,
            )
            cache_openai_models(data, parse_available_models(raw))
            return {"object": "list", "data": data}
        except NotionChatError as e:
            stale = get_stale_cached_openai_models()
            if stale is not None:
                log.warning("getAvailableModels failed (%s), using stale cached models", e)
                return {"object": "list", "data": stale}
            log.error("getAvailableModels failed and no cache exists: %s", e)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch models from upstream Notion AI: {e}",
            ) from e
        finally:
            await client.aclose()

    async def _run_chat_completion(
        req: ChatCompletionRequest,
        x_content_generation: str | None,
    ) -> dict[str, Any]:
        """Core non-streaming chat completion logic.

        Shared by /v1/chat/completions (non-streaming path) and
        /v1/responses. Streaming and HTTP error translation stay in the
        route handlers.
        """
        session_lock = await _get_session_lock(_session_lock_key(req, settings))
        async with session_lock:
            tools = normalize_tools(_tools_payload(req))
            content_mode = bool(x_content_generation)
            system, prompt, tools_active, ide_agent, tools = prepare_chat_input(
                req.messages,
                tools=tools,
                tool_choice=req.tool_choice,
                content_mode=content_mode,
            )
            if not tools and is_ide_agent_messages(req.messages):
                log.warning("Cursor-like request but tools[] empty after prepare_chat_input")
            client = get_client()
            try:
                # Prefetch aliases before resolve/log so names like glm-5.2 map cleanly.
                await _ensure_model_aliases(client, settings)
                log.info(
                    "chat stream=%s model=%s resolved=%s tools=%d tools_active=%s ide_agent=%s tool_names=%s msgs=%d",
                    req.stream,
                    normalize_request_model(req.model) or req.model,
                    _resolved_request_model(req, settings),
                    len(tools),
                    tools_active,
                    ide_agent,
                    sorted(client_tool_names(tools))[:8],
                    len(req.messages),
                )
                thread_id = _resolve_request_thread(
                    req,
                    settings,
                    ide_agent=ide_agent,
                    tools_active=tools_active,
                )
                result = await client.complete(
                    prompt=prompt,
                    system=system,
                    model=req.model,
                    thread_id=thread_id,
                    tools_active=tools_active,
                    ide_agent_mode=ide_agent,
                    client_tools=tools,
                )
                result = await _bridge_ide_agent_async(
                    client,
                    result,
                    req=req,
                    tools=tools,
                    prompt=prompt,
                    system=system,
                    ide_agent=ide_agent,
                    tools_active=tools_active,
                )
                log.info(
                    "chat result text_len=%s tool_calls=%s",
                    len(result.text or ""),
                    [((tc.get("function") or {}).get("name")) for tc in (result.tool_calls or [])],
                )
                _remember_request_thread(
                    req,
                    result.thread_id,
                    settings,
                    ide_agent=ide_agent,
                    tools_active=tools_active,
                )
                completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                finish_reason = "tool_calls" if result.tool_calls else "stop"
                return {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": req.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": _assistant_message(result),
                            "finish_reason": finish_reason,
                        }
                    ],
                    "usage": _usage(result),
                }
            finally:
                await client.aclose()

    @app.post("/v1/chat/completions")
    async def chat_completions(
        req: ChatCompletionRequest,
        _: None = Depends(verify_key),
        x_content_generation: str | None = Header(None, alias="X-Content-Generation"),
        x_allow_stream_replace: str | None = Header(None, alias="X-Allow-Stream-Replace"),
    ) -> Any:
        try:
            if req.stream:
                # Streaming path stays in-line because it returns SSE chunks,
                # not a serializable dict.
                allow_replace = bool(
                    x_allow_stream_replace
                    and x_allow_stream_replace.strip().lower() in ("1", "true", "yes")
                )
                tools = normalize_tools(_tools_payload(req))
                content_mode = bool(x_content_generation)
                system, prompt, tools_active, ide_agent, tools = prepare_chat_input(
                    req.messages,
                    tools=tools,
                    tool_choice=req.tool_choice,
                    content_mode=content_mode,
                )
                client = get_client()
                try:
                    await _ensure_model_aliases(client, settings)
                    thread_id = _resolve_request_thread(
                        req,
                        settings,
                        ide_agent=ide_agent,
                        tools_active=tools_active,
                    )
                    return StreamingResponse(
                        _stream_openai(
                            client,
                            req,
                            system,
                            prompt,
                            thread_id,
                            settings,
                            tools=tools,
                            tools_active=tools_active,
                            ide_agent=ide_agent,
                            content_mode=content_mode,
                            allow_stream_replace=allow_replace,
                        ),
                        media_type="text/event-stream",
                    )
                finally:
                    pass  # client kept alive by _stream_openai
            return await _run_chat_completion(req, x_content_generation)
        except NotionChatError as e:
            if e.status_code == 403:
                log.warning("chat/completions 403: %s", e)
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    @app.post("/v1/responses")
    async def responses_endpoint(
        req: ResponsesRequest,
        _: None = Depends(verify_key),
        x_content_generation: str | None = Header(None, alias="X-Content-Generation"),
    ) -> Any:
        """OpenAI Responses API compatibility shim (issue #4).

        Claude Code / Codex / newer OpenAI SDKs send chat requests to
        /v1/responses with a slightly different shape than
        /v1/chat/completions. We translate into Chat Completions, run the
        same Notion pipeline, then re-shape the response back.

        Non-streaming only in v1 -- streaming Responses SSE differs enough
        (response.output_text.delta events, etc.) that it deserves its own
        follow-up rather than a half-baked translation.
        """
        if req.stream:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Streaming is not yet supported on /v1/responses. "
                    "Disable stream=true or use /v1/chat/completions."
                ),
            )
        if req.previous_response_id:
            raise HTTPException(
                status_code=400,
                detail="previous_response_id is not yet supported in this version.",
            )
        try:
            chat_req = _responses_to_chat(req)
            chat_resp = await _run_chat_completion(chat_req, x_content_generation)
            return _chat_to_responses(chat_resp, chat_req.model)
        except NotionChatError as e:
            if e.status_code == 403:
                log.warning("responses 403: %s", e)
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    return app
