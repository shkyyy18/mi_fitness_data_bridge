from __future__ import annotations

import asyncio

from mi_fitness_mcp import server
from mi_fitness_mcp.config import Config


class _FakeAdapter:
    def __init__(self, user_id):
        self._user_id = user_id

    def is_connected(self):
        return True

    def get_user_id(self):
        return self._user_id


def test_get_profile_returns_masked_account_id(monkeypatch):
    monkeypatch.setattr(server, "adapter", _FakeAdapter("1234567890"))
    monkeypatch.setattr(
        server, "config", Config(mode="mi_fitness_cloud", timezone="Asia/Shanghai")
    )

    result = asyncio.run(server._handle_get_profile())

    profile = result["data"]["profile"]
    assert profile["account_id_masked"] == "******90"
    assert "user_id" not in profile
    assert "1234567890" not in str(profile)
    assert profile["timezone"] == "Asia/Shanghai"


def test_mask_account_id_unified_format_between_server_and_cli():
    # server 与 CLI 共用 auth.mask_account_id：固定 6 个星号、只留末 2 位。
    from mi_fitness_mcp.auth import mask_account_id

    assert mask_account_id(None) is None
    assert mask_account_id("") is None
    assert mask_account_id("  ") is None
    assert mask_account_id("ab") == "******"
    assert mask_account_id("12345") == "******45"
    assert mask_account_id("1234567890") == "******90"
    assert server.mask_account_id is mask_account_id
