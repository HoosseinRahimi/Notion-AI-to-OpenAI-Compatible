from __future__ import annotations

import os
import re
from typing import Any

from notionchat.account import NotionAccount, build_cookie_header

# Keep in sync with a recent Notion web client (update via init --client-version).
DEFAULT_CLIENT_VERSION = "23.13.20260710.0022"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

_CHROME_MAJOR_RE = re.compile(r"Chrome/(\d+)", re.IGNORECASE)
_IMPERSONATE_BY_MAJOR: tuple[tuple[int, str], ...] = (
    (136, "chrome136"),
    (131, "chrome131"),
    (124, "chrome124"),
    (120, "chrome120"),
    (116, "chrome116"),
    (110, "chrome110"),
    (0, "chrome"),
)


def chrome_major_from_ua(user_agent: str) -> int | None:
    match = _CHROME_MAJOR_RE.search(user_agent or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def sec_ch_ua_from_user_agent(user_agent: str) -> str:
    major = chrome_major_from_ua(user_agent) or 150
    # Match current Chrome client hints shape seen on app.notion.com.
    return f'"Not;A=Brand";v="8", "Chromium";v="{major}", "Google Chrome";v="{major}"'


def impersonate_for_user_agent(user_agent: str) -> str:
    override = os.getenv("NOTION_IMPERSONATE", "").strip()
    if override:
        return override
    major = chrome_major_from_ua(user_agent) or 120
    for threshold, target in _IMPERSONATE_BY_MAJOR:
        if major >= threshold:
            return target
    return "chrome"


def resolve_client_version(acc: NotionAccount) -> str:
    env = os.getenv("NOTION_CLIENT_VERSION", "").strip()
    if env:
        return env
    if acc.client_version:
        return acc.client_version
    return DEFAULT_CLIENT_VERSION


def resolve_user_agent(acc: NotionAccount) -> str:
    env = os.getenv("NOTION_USER_AGENT", "").strip()
    if env:
        return env
    if acc.user_agent:
        return acc.user_agent
    return DEFAULT_USER_AGENT


def resolve_sec_ch_ua(acc: NotionAccount, user_agent: str) -> str:
    env = os.getenv("NOTION_SEC_CH_UA", "").strip()
    if env:
        return env
    extra = acc.extras.get("sec_ch_ua") if acc.extras else None
    if isinstance(extra, str) and extra.strip():
        return extra.strip()
    return sec_ch_ua_from_user_agent(user_agent)


def build_notion_request_headers(
    acc: NotionAccount,
    *,
    accept: str = "application/x-ndjson",
    referer: str = "https://app.notion.com/chat",
) -> dict[str, str]:
    """Build browser-like headers aligned with the account fingerprint."""
    user_agent = resolve_user_agent(acc)
    headers: dict[str, Any] = {
        "accept": accept,
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "notion-audit-log-platform": "web",
        "notion-client-version": resolve_client_version(acc),
        "origin": "https://app.notion.com",
        "referer": referer,
        "user-agent": user_agent,
        "x-notion-active-user-header": acc.user_id,
        "x-notion-space-id": acc.space_id,
        "sec-ch-ua": resolve_sec_ch_ua(acc, user_agent),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "priority": "u=1, i",
        "cookie": build_cookie_header(acc),
    }
    return {k: str(v) for k, v in headers.items() if v}


def fingerprint_kwargs(
    *,
    user_agent: str | None = None,
    client_version: str | None = None,
) -> dict[str, str]:
    ua = user_agent or os.getenv("NOTION_USER_AGENT", "").strip() or DEFAULT_USER_AGENT
    cv = client_version or os.getenv("NOTION_CLIENT_VERSION", "").strip() or DEFAULT_CLIENT_VERSION
    return {
        "user_agent": ua,
        "client_version": cv,
        "sec_ch_ua": sec_ch_ua_from_user_agent(ua),
        "impersonate": impersonate_for_user_agent(ua),
    }
