from __future__ import annotations

from pathlib import Path

import pytest

from notionchat.account import (
    NotionAccount,
    build_cookie_header,
    load_notion_account,
    parse_browser_cookie,
    save_notion_account,
)
from notionchat.exceptions import NotionChatError


def test_parse_browser_cookie():
    cookie_str = "token_v2=abc; notion_user_id=usr-123; notion_browser_id=br-456; other_val=xyz"
    parsed = parse_browser_cookie(cookie_str)
    assert parsed["token_v2"] == "abc"
    assert parsed["notion_user_id"] == "usr-123"
    assert parsed["notion_browser_id"] == "br-456"
    assert parsed["other_val"] == "xyz"


def test_build_cookie_header_full_cookie():
    acc = NotionAccount(token_v2="tok", full_cookie="token_v2=tok; foo=bar")
    header = build_cookie_header(acc)
    assert header == "token_v2=tok; foo=bar"


def test_build_cookie_header_fallback():
    acc = NotionAccount(
        token_v2="tok123",
        browser_id="b1",
        device_id="d1",
        user_id="u1",
    )
    header = build_cookie_header(acc)
    assert "token_v2=tok123" in header
    assert "notion_user_id=u1" in header
    assert "notion_browser_id=b1" in header
    assert "device_id=d1" in header


def test_account_save_and_load(tmp_path: Path):
    acc = NotionAccount(
        token_v2="tok-abc",
        user_id="usr-123",
        space_id="spc-456",
        user_name="John Doe",
        extras={"custom_field": 42},
    )
    path = tmp_path / "account.json"
    save_notion_account(acc, path)

    loaded = load_notion_account(path)
    assert loaded.token_v2 == "tok-abc"
    assert loaded.user_id == "usr-123"
    assert loaded.space_id == "spc-456"
    assert loaded.user_name == "John Doe"
    assert loaded.extras["custom_field"] == 42


def test_load_nonexistent_account(tmp_path: Path):
    with pytest.raises(NotionChatError) as exc_info:
        load_notion_account(tmp_path / "nonexistent.json")
    assert exc_info.value.status_code == 500


def test_load_invalid_json_account(tmp_path: Path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json", encoding="utf-8")
    with pytest.raises(NotionChatError) as exc_info:
        load_notion_account(bad_file)
    assert exc_info.value.status_code == 500
