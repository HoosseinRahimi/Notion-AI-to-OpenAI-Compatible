from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from typing import Any, cast
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession, Response

from notionchat.browser_fp import impersonate_for_user_agent

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300.0


def resolve_notion_proxy() -> str | None:
    """HTTP(S)/SOCKS proxy for Notion egress (local cookie on a VPS needs home IP)."""
    for key in (
        "NOTION_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def _proxy_log_label(proxy: str) -> str:
    """Redact credentials for logs."""
    try:
        parts = urlsplit(proxy)
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme or 'proxy'}://{host}{port}"
    except Exception:
        return "(proxy)"


# --- curl_cffi 0.15.0 + Python 3.14 workaround ---------------------------------
# The AsyncCurl._pop_future method calls lib.curl_multi_remove_handle with
# curl._curl, which can be None during cleanup callbacks, raising
# "TypeError: initializer for ctype 'void *' must be a cdata pointer, not NoneType".
# Monkey-patch it to skip None handles. Applied once at import.
try:
    from curl_cffi._wrapper import lib  # type: ignore
    from curl_cffi.aio import AsyncCurl as _AsyncCurl

    _original_pop_future = _AsyncCurl._pop_future

    def _safe_pop_future(self, curl):  # noqa: ANN001, ANN202
        curl_ptr = getattr(curl, "_curl", None)
        if curl_ptr is None or self._curlm is None:
            return self._curl2future.pop(curl, None)
        errcode = lib.curl_multi_remove_handle(self._curlm, curl_ptr)
        with suppress(Exception):
            self._check_error(errcode)
        self._curl2curl.pop(curl_ptr, None)
        return self._curl2future.pop(curl, None)

    if getattr(_original_pop_future, "__name__", "") != "_safe_pop_future":
        _AsyncCurl._pop_future = _safe_pop_future
        log.debug("Patched AsyncCurl._pop_future for curl_cffi 0.15.0 NoneType bug")
except Exception as _patch_err:  # pragma: no cover
    log.warning("Could not patch curl_cffi AsyncCurl: %s", _patch_err)
# -----------------------------------------------------------------------------


class NotionHttpStatusError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body[:200]!r}")


class NotionStreamResponse:
    """Wrapper around curl_cffi Response that owns its session for cleanup."""

    __slots__ = ("_resp", "_session", "_closed")

    def __init__(self, resp: Response, session: AsyncSession) -> None:
        self._resp = resp
        self._session = session
        self._closed = False

    @property
    def status_code(self) -> int:
        return self._resp.status_code

    async def aiter_lines(self):  # noqa: ANN202
        async for line in self._resp.aiter_lines():
            yield line

    async def atext(self) -> str:
        return await self._resp.atext()

    def json(self) -> Any:
        return self._resp.json()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        resp = self._resp
        # Abort an in-flight body so curl_cffi's perform() can finish.
        # Sync Response.close() sets quit_now but never awaits astream_task —
        # that leaves orphaned Tasks ("Task was destroyed but it is pending!").
        with suppress(Exception):
            quit_now = getattr(resp, "quit_now", None)
            if quit_now is not None and not quit_now.is_set():
                quit_now.set()
        stream_task = getattr(resp, "astream_task", None)
        if stream_task is not None:
            with suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
                await asyncio.wait_for(stream_task, timeout=5.0)
            with suppress(Exception):
                resp.astream_task = None
        else:
            with suppress(Exception):
                resp.close()
        with suppress(Exception):
            await self._session.close()
        # Let curl_cffi cleanup callbacks scheduled by release_curl run.
        for _ in range(2):
            await asyncio.sleep(0)

    def close(self) -> None:
        """Sync close — prefer aclose() on the event loop."""
        if self._closed:
            return
        self._closed = True
        with suppress(Exception):
            quit_now = getattr(self._resp, "quit_now", None)
            if quit_now is not None and not quit_now.is_set():
                quit_now.set()
        with suppress(Exception):
            self._resp.close()


class NotionHttpClient:
    """Impersonates Chrome TLS — required for Notion AI on Business plans.

    Each request gets a fresh AsyncSession to avoid curl_cffi socket-pipe
    corruption on Windows ProactorEventLoop (WinError 10054). Sessions are
    closed after the response is consumed.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        impersonate: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._impersonate = impersonate
        self._proxy = proxy if proxy is not None else resolve_notion_proxy()
        if self._proxy:
            log.info("Notion HTTP egress via proxy %s", _proxy_log_label(self._proxy))

    async def aclose(self) -> None:
        return

    def _resolve_impersonate(self, headers: dict[str, str]) -> str:
        if self._impersonate:
            return self._impersonate
        return impersonate_for_user_agent(headers.get("user-agent", ""))

    async def _request(
        self,
        url: str,
        *,
        method: str,
        json: dict[str, Any],
        headers: dict[str, str],
        stream: bool,
    ) -> NotionStreamResponse:
        session_kwargs: dict[str, Any] = {"timeout": self._timeout}
        if self._proxy:
            session_kwargs["proxy"] = self._proxy
        session = AsyncSession(**session_kwargs)
        impersonate = self._resolve_impersonate(headers)
        log.debug(
            "Notion HTTP impersonate=%s ua=%s", impersonate, headers.get("user-agent", "")[:60]
        )
        try:
            resp = await session.request(
                cast(Any, method),
                url,
                json=json,
                headers=headers,
                impersonate=cast(Any, impersonate),
                stream=stream,
            )
            return NotionStreamResponse(resp, session)
        except BaseException:
            with suppress(Exception):
                await session.close()
            for _ in range(2):
                with suppress(Exception):
                    await asyncio.sleep(0)
            raise

    async def post_json(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
        wrapper = await self._request(
            url,
            method="POST",
            json=json,
            headers=headers,
            stream=False,
        )
        try:
            if wrapper.status_code != 200:
                raise NotionHttpStatusError(wrapper.status_code, await wrapper.atext())
            return wrapper.json()
        finally:
            await wrapper.aclose()

    async def post_stream(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> NotionStreamResponse:
        return await self._request(
            url,
            method="POST",
            json=json,
            headers=headers,
            stream=True,
        )
