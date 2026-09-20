from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from notionchat.account import NotionAccount, save_notion_account
from notionchat.client import NotionAIClient
from notionchat.config import Settings, validate_settings_security
from notionchat.exceptions import NotionChatError
from notionchat.openai_api import create_app
from notionchat.setup_cli import _write_env
from notionchat.thread_state import ThreadState, save_thread_state


def test_public_bind_with_default_key_rejected(tmp_path: Path):
    settings = Settings(
        api_key="sk-notionchat",
        host="0.0.0.0",
        port=1994,
        account_path=tmp_path / "account.json",
        thread_state_dir=tmp_path / "threads",
        base_url="https://app.notion.com/api/v3",
        default_model="ambrosia-tart-high",
        thread_reuse_limit=0,
    )
    with pytest.raises(NotionChatError) as exc_info:
        validate_settings_security(settings)
    assert exc_info.value.status_code == 500
    assert "Refusing to bind to non-loopback host" in str(exc_info.value)


def test_public_bind_with_empty_key_rejected(tmp_path: Path):
    settings = Settings(
        api_key="",
        host="192.168.1.100",
        port=1994,
        account_path=tmp_path / "account.json",
        thread_state_dir=tmp_path / "threads",
        base_url="https://app.notion.com/api/v3",
        default_model="ambrosia-tart-high",
        thread_reuse_limit=0,
    )
    with pytest.raises(NotionChatError):
        validate_settings_security(settings)


def test_public_bind_with_strong_key_allowed(tmp_path: Path):
    settings = Settings(
        api_key="sk-strong-secret-key-987654321",
        host="0.0.0.0",
        port=1994,
        account_path=tmp_path / "account.json",
        thread_state_dir=tmp_path / "threads",
        base_url="https://app.notion.com/api/v3",
        default_model="ambrosia-tart-high",
        thread_reuse_limit=0,
    )
    # Should not raise
    validate_settings_security(settings)


def test_loopback_bind_with_default_key_allowed(tmp_path: Path):
    settings = Settings(
        api_key="sk-notionchat",
        host="127.0.0.1",
        port=1994,
        account_path=tmp_path / "account.json",
        thread_state_dir=tmp_path / "threads",
        base_url="https://app.notion.com/api/v3",
        default_model="ambrosia-tart-high",
        thread_reuse_limit=0,
    )
    # Should not raise
    validate_settings_security(settings)


@pytest.mark.asyncio
async def test_timing_safe_key_verification(test_settings: Settings):
    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid key
        resp = await client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid API key"

        # Valid key
        resp = await client.get(
            "/v1/models", headers={"Authorization": f"Bearer {test_settings.api_key}"}
        )
        # Should get past auth check (200 with cached/static models or error from fetch, but not 401)
        assert resp.status_code != 401


def test_atomic_account_write(tmp_path: Path):
    acc = NotionAccount(token_v2="token-xyz", user_id="user-1", space_id="space-1")
    path = tmp_path / "notion_account.json"
    save_notion_account(acc, path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["token_v2"] == "token-xyz"


def test_atomic_thread_state_write(tmp_path: Path):
    state = ThreadState(
        thread_id="th-123",
        config_id="cfg-1",
        context_id="ctx-1",
        original_datetime="2026-09-20T00:00:00Z",
        notion_model="claude-3.5-sonnet",
    )
    p = save_thread_state(state, tmp_path)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["thread_id"] == "th-123"


def test_write_env_preserves_comments_and_unmanaged_keys(tmp_path: Path):
    env_file = tmp_path / ".env"
    initial_content = (
        "# Important configuration\n"
        "NOTION_PROXY=http://127.0.0.1:8080\n"
        "# Another comment\n"
        "NOTIONCHAT_PORT=8787\n"
        "CUSTOM_VAR=keep_me\n"
    )
    env_file.write_text(initial_content, encoding="utf-8")

    updates = {
        "NOTIONCHAT_PORT": "1994",
        "NOTIONCHAT_API_KEY": "sk-new-key",
    }
    _write_env(env_file, updates, overwrite=False)

    # Check backup was created
    backup_file = env_file.with_suffix(".env.bak")
    assert backup_file.exists()
    assert backup_file.read_text(encoding="utf-8") == initial_content

    # Check content preserved
    new_content = env_file.read_text(encoding="utf-8")
    assert "# Important configuration" in new_content
    assert "NOTION_PROXY=http://127.0.0.1:8080" in new_content
    assert "CUSTOM_VAR=keep_me" in new_content
    assert "NOTIONCHAT_PORT=1994" in new_content
    assert "NOTIONCHAT_API_KEY=sk-new-key" in new_content


def test_error_sanitization_does_not_leak_raw_body(mock_account: NotionAccount, tmp_path: Path):
    client = NotionAIClient(
        mock_account, base_url="https://app.notion.com/api/v3", thread_state_dir=tmp_path
    )
    sensitive_body = "<html><body>Error: User token_v2=SECRET_TOKEN was rejected by workspace SEC_WORKSPACE</body></html>"

    with pytest.raises(NotionChatError) as exc_401:
        client._raise_http(401, sensitive_body)
    assert "SECRET_TOKEN" not in str(exc_401.value)
    assert "SEC_WORKSPACE" not in str(exc_401.value)

    with pytest.raises(NotionChatError) as exc_502:
        client._raise_http(500, sensitive_body)
    assert "SECRET_TOKEN" not in str(exc_502.value)
    assert "SEC_WORKSPACE" not in str(exc_502.value)
