"""Synthetic protocol regressions. All HTTP and keyring access is mocked."""

import asyncio
import base64
import json
import traceback

import httpx
import pytest
import respx

from mi_fitness_mcp.adapters import mi_fitness_cloud as cloud

LOGIN = "https://account.xiaomi.com/pass/serviceLogin?_json=true&sid=miothealth"
REDIRECT = "https://sts.api.mi.com/auth2?ticket=synthetic-secret"
SECRET = "synthetic-secret"


def payload():
    return {
        "passToken": "synthetic-new-token",
        "userId": 12345,
        "ssecurity": base64.b64encode(b"synthetic-key").decode(),
        "location": REDIRECT,
    }


@pytest.fixture
def saved(monkeypatch):
    values = []
    monkeypatch.setattr(cloud, "save_mi_fitness_token", lambda *args: values.append(args))
    return values


def login(text, status=200, cookies="serviceToken=synthetic-cookie"):
    adapter = cloud.MiFitnessCloudAdapter(user_id="synthetic-user", pass_token="synthetic-token")

    async def run():
        with respx.mock(assert_all_called=False) as mock:
            mock.get(LOGIN).respond(200, text=text)
            route = mock.get(REDIRECT).respond(status, headers={"set-cookie": cookies})
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                adapter._client = client
                try:
                    await adapter._login_with_token(adapter.user_id, adapter.pass_token)
                except cloud.MiFitnessAuthenticationError as exc:
                    return adapter, exc, route.called
                return adapter, None, route.called

    return asyncio.run(run())


@pytest.mark.parametrize(
    "text",
    [
        "unexpected " + SECRET,
        "&&&START&&&{" + SECRET,
        "&&&START&&&[]",
        "&&&START&&&null",
        "&&&START&&&42",
    ],
)
def test_malformed_response_is_safe(text, saved):
    adapter, error, followed = login(text)
    assert error is not None
    assert SECRET not in "".join(traceback.format_exception(error))
    assert not followed and not saved
    assert adapter.pass_token == "synthetic-token"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("passToken", {"value": SECRET}),
        ("userId", True),
        ("userId", [SECRET]),
        ("ssecurity", [SECRET]),
        ("ssecurity", "invalid!"),
        ("passToken", "bad;token"),
        ("location", {"url": SECRET}),
        ("location", "https://[malformed/" + SECRET),
        ("location", "https://evil.invalid/?ticket=" + SECRET),
        ("location", "https://user:synthetic-secret@mi.com/"),
        ("location", "https://mi.com:invalid/" + SECRET),
        ("location", "https://mi.com:8443/" + SECRET),
        ("location", "https://mi.com/\n" + SECRET),
    ],
)
def test_invalid_fields_do_not_mutate_state_or_leak(field, value, saved):
    body = payload()
    body[field] = value
    adapter, error, followed = login("&&&START&&&" + json.dumps(body))
    assert error is not None
    assert SECRET not in "".join(traceback.format_exception(error))
    assert not followed and not saved
    assert adapter.pass_token == "synthetic-token"
    assert adapter.user_id == "synthetic-user"
    assert adapter._ssecurity == b""


def test_server_error_description_is_not_logged(saved):
    _, error, followed = login("&&&START&&&" + json.dumps({"description": SECRET}))
    assert error is not None
    assert SECRET not in str(error)
    assert not followed and not saved


def test_valid_rotation_survives_redirect_failure_without_url_disclosure(saved):
    adapter, error, followed = login("&&&START&&&" + json.dumps(payload()), status=503)
    assert error is not None and followed
    assert SECRET not in "".join(traceback.format_exception(error))
    assert saved == [("12345", "synthetic-new-token")]
    assert adapter.pass_token == "synthetic-new-token"
    assert adapter._cookies == ""


def test_missing_session_cookie_is_not_success(saved):
    _, error, followed = login("&&&START&&&" + json.dumps(payload()), cookies="unrelated=value")
    assert error is not None and followed
    assert "serviceToken" in str(error)


def test_mocked_success_persists_rotation(saved):
    adapter, error, followed = login("&&&START&&&" + json.dumps(payload()))
    assert error is None and followed
    assert adapter._cookies == "serviceToken=synthetic-cookie"
    assert saved == [("12345", "synthetic-new-token")]


def test_keyring_failure_does_not_disclose_exception(saved, monkeypatch, caplog):
    def fail(*args):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(cloud, "save_mi_fitness_token", fail)
    _, error, followed = login("&&&START&&&" + json.dumps(payload()))
    assert error is None and followed
    assert "Failed to persist" in caplog.text
    assert SECRET not in caplog.text
