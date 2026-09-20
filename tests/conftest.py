from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from notionchat.account import NotionAccount
from notionchat.config import Settings
from notionchat.openai_api import create_app


@pytest.fixture
def mock_account() -> NotionAccount:
    return NotionAccount(
        token_v2="mock-token-v2",
        full_cookie="token_v2=mock-token-v2; notion_user_id=mock-user-id; notion_browser_id=mock-browser-id;",
        user_id="mock-user-id",
        user_name="Test User",
        user_email="test@example.com",
        space_id="mock-space-id",
        space_name="Test Workspace",
        space_view_id="mock-space-view-id",
        browser_id="mock-browser-id",
        device_id="mock-device-id",
    )


@pytest.fixture
def test_settings(tmp_path: Path, mock_account: NotionAccount) -> Settings:
    from notionchat.account import save_notion_account

    acc_path = tmp_path / "notion_account.json"
    save_notion_account(mock_account, acc_path)
    threads_dir = tmp_path / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        api_key="sk-test-key-12345",
        host="127.0.0.1",
        port=1994,
        account_path=acc_path,
        thread_state_dir=threads_dir,
        base_url="https://app.notion.com/api/v3",
        default_model="ambrosia-tart-high",
        thread_reuse_limit=0,
    )


@pytest.fixture
def mock_models_payload() -> dict[str, Any]:
    return {
        "models": [
            {
                "model": "ambrosia-tart-high",
                "modelMessage": "claude-3.5-sonnet",
                "isDisabled": False,
            },
            {
                "model": "ambrosia-tart-low",
                "modelMessage": "claude-3.5-haiku",
                "isDisabled": False,
            },
            {
                "model": "disabled-model",
                "modelMessage": "gpt-4-disabled",
                "isDisabled": True,
            },
        ]
    }


@pytest.fixture
async def app_client(test_settings: Settings) -> AsyncClient:
    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
