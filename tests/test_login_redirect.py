"""Regression tests: the Xiaomi login redirect `location` is server-controlled
input and must be validated against an allowlist of Xiaomi-owned HTTPS hosts
before it is followed (SSRF / credential-leak guard).
"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from mi_fitness_mcp.adapters import mi_fitness_cloud
from mi_fitness_mcp.adapters.mi_fitness_cloud import (
    LOGIN_PREFIX,
    MiFitnessCloudAdapter,
    _is_allowed_login_redirect,
)


@pytest.fixture(autouse=True)
def _no_real_keyring_write(monkeypatch):
    """Login now persists the rotated passToken; never touch the real keyring."""
    saved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mi_fitness_cloud,
        "save_mi_fitness_token",
        lambda user_id, pass_token: saved.append((user_id, pass_token)),
    )
    return saved


@pytest.mark.parametrize(
    "url",
    [
        "https://account.xiaomi.com/pass/serviceLoginAuth2",
        "https://sts.api.mi.com/x",
        "https://xiaomi.com/",
        "https://mi.com/",
    ],
)
def test_login_redirect_allowlist_accepts_xiaomi_https(url):
    assert _is_allowed_login_redirect(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.com",
        "http://account.xiaomi.com/pass/serviceLoginAuth2",  # plain HTTP
        "https://evil.com",
        "https://xiaomi.com.evil.com/x",  # lookalike suffix attack
        "https://notmi.com/x",
        "not-a-url",
        "",
    ],
)
def test_login_redirect_allowlist_rejects_untrusted(url):
    assert _is_allowed_login_redirect(url) is False


class _FakeResponse:
    def __init__(self, text: str = "", headers: httpx.Headers | None = None):
        self.text = text
        self.headers = headers or httpx.Headers()

    def raise_for_status(self) -> None:
        return None


class _RecordingClient:
    """Serves a synthetic login payload, then records any redirect request."""

    def __init__(self, login_location: str):
        self.requested_urls: list[str] = []
        payload = {
            "passToken": "synthetic-new-token",
            "userId": 12345,
            "ssecurity": base64.b64encode(b"synthetic-ssecurity").decode(),
            "location": login_location,
        }
        self._login_text = LOGIN_PREFIX.decode() + json.dumps(payload)

    async def get(self, url: str, **kwargs) -> _FakeResponse:
        self.requested_urls.append(url)
        if "serviceLogin" in url:
            return _FakeResponse(text=self._login_text)
        return _FakeResponse(
            headers=httpx.Headers({"set-cookie": "serviceToken=abc; Path=/"})
        )


def test_login_rejects_malicious_redirect_without_following_it():
    adapter = MiFitnessCloudAdapter(user_id="synthetic-user", pass_token="synthetic-token")
    client = _RecordingClient("http://evil.com/steal?c=1")
    adapter._client = client

    with pytest.raises(RuntimeError, match="Refusing untrusted login redirect"):
        asyncio.run(adapter._login_with_token("synthetic-user", "synthetic-token"))

    # Only the initial serviceLogin request may have happened.
    assert len(client.requested_urls) == 1
    assert "serviceLogin" in client.requested_urls[0]


def test_login_follows_allowed_xiaomi_redirect():
    adapter = MiFitnessCloudAdapter(user_id="synthetic-user", pass_token="synthetic-token")
    client = _RecordingClient("https://sts.api.mi.com/auth2")
    adapter._client = client

    asyncio.run(adapter._login_with_token("synthetic-user", "synthetic-token"))

    assert client.requested_urls[-1] == "https://sts.api.mi.com/auth2"
    assert adapter._cookies == "serviceToken=abc"
    assert adapter.pass_token == "synthetic-new-token"


def test_login_persists_rotated_pass_token_to_keyring(_no_real_keyring_write):
    adapter = MiFitnessCloudAdapter(user_id="synthetic-user", pass_token="synthetic-token")
    adapter._client = _RecordingClient("https://sts.api.mi.com/auth2")

    asyncio.run(adapter._login_with_token("synthetic-user", "synthetic-token"))

    # 登录轮换了 passToken（synthetic-token -> synthetic-new-token），必须写回 keyring。
    assert _no_real_keyring_write == [("12345", "synthetic-new-token")]


def test_login_token_persistence_failure_does_not_break_sync(monkeypatch):
    adapter = MiFitnessCloudAdapter(user_id="synthetic-user", pass_token="synthetic-token")
    adapter._client = _RecordingClient("https://sts.api.mi.com/auth2")

    def failing_save(user_id, pass_token):
        raise RuntimeError("synthetic keyring write failure")

    monkeypatch.setattr(mi_fitness_cloud, "save_mi_fitness_token", failing_save)

    # 写 keyring 失败只记 warning，登录流程本身仍然成功。
    asyncio.run(adapter._login_with_token("synthetic-user", "synthetic-token"))
    assert adapter.pass_token == "synthetic-new-token"
