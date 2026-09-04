from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from mi_fitness_mcp import main as cli
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.auth import keyring_backend_warning
from mi_fitness_mcp.config import Config


def test_config_and_adapter_default_to_china_region():
    assert Config().region == "cn"
    adapter = MiFitnessCloudAdapter(user_id="synthetic-user", pass_token="synthetic-token")
    assert adapter.region == "cn"


def test_cloud_adapter_receives_runtime_limits():
    config = Config(
        mode="mi_fitness_cloud",
        http_timeout_seconds=12.5,
        request_retries=4,
        max_pages=321,
    )

    adapter = cli._create_cloud_adapter("synthetic-user", "synthetic-token", config)

    assert adapter.http_timeout == 12.5
    assert adapter.request_retries == 4
    assert adapter.max_pages == 321


def test_interactive_setup_hides_pass_token(monkeypatch):
    answers = iter(["synthetic-user", "cn"])
    input_prompts: list[str] = []
    secret_prompts: list[str] = []
    saved: dict[str, object] = {}

    def fake_input(prompt: str) -> str:
        input_prompts.append(prompt)
        return next(answers)

    def fake_getpass(prompt: str) -> str:
        secret_prompts.append(prompt)
        return "synthetic-token"

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)
    monkeypatch.setattr(
        cli,
        "save_mi_fitness_token",
        lambda user_id, pass_token: saved.update(user_id=user_id, pass_token=pass_token),
    )
    monkeypatch.setattr(cli, "save_config", lambda config: saved.update(config=config))

    cli.cmd_setup(SimpleNamespace(mode=None, user_id=None, pass_token=None, region=None))

    assert len(input_prompts) == 2
    assert len(secret_prompts) == 1
    assert "passToken" in secret_prompts[0]
    assert saved["user_id"] == "synthetic-user"
    assert saved["pass_token"] == "synthetic-token"
    assert saved["config"].region == "cn"


def test_setup_rejects_credential_cli_flags(monkeypatch):
    """--user-id/--pass-token were removed: passTokens must not enter shell history."""
    monkeypatch.setattr(
        sys, "argv", ["mi-fitness-bridge", "setup", "--pass-token", "synthetic-token"]
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2  # argparse usage error


def test_keyring_backend_warning_flags_weak_backend(monkeypatch):
    import keyring.backends.fail

    monkeypatch.setattr("keyring.get_keyring", lambda: keyring.backends.fail.Keyring())
    warning = keyring_backend_warning()
    assert warning is not None
    assert "fail" in warning


def test_keyring_backend_warning_quiet_for_strong_backend(monkeypatch):
    class FakeWinVaultBackend:
        pass

    monkeypatch.setattr("keyring.get_keyring", lambda: FakeWinVaultBackend())
    assert keyring_backend_warning() is None


def test_keyring_backend_warning_reports_unknown_backend(monkeypatch):
    def _raise():
        raise RuntimeError("synthetic keyring failure")

    monkeypatch.setattr("keyring.get_keyring", _raise)
    warning = keyring_backend_warning()
    assert warning is not None
    assert "无法确定" in warning


def test_setup_prints_weak_keyring_warning(monkeypatch, capsys):
    answers = iter(["synthetic-user", "cn"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "synthetic-token")
    monkeypatch.setattr(cli, "save_mi_fitness_token", lambda *args: None)
    monkeypatch.setattr(cli, "save_config", lambda config: None)
    monkeypatch.setattr(cli, "keyring_backend_warning", lambda: "synthetic weak backend")

    cli.cmd_setup(SimpleNamespace(mode=None, region=None))

    assert "synthetic weak backend" in capsys.readouterr().out



def test_doctor_exits_nonzero_when_credentials_are_missing(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "get_config_path", lambda: config_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(mode="mi_fitness_cloud", database_path=tmp_path / "mi_fitness.db"),
    )
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: (None, None))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_doctor(SimpleNamespace())

    assert exc_info.value.code == 1
    assert "未找到 Mi Fitness 凭据" in capsys.readouterr().out


def test_doctor_exits_nonzero_when_cloud_connection_fails(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    closed: list[bool] = []

    class DisconnectedAdapter:
        region = "cn"

        async def connect(self):
            return False

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(cli, "get_config_path", lambda: config_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(mode="mi_fitness_cloud", database_path=tmp_path / "mi_fitness.db"),
    )
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: ("synthetic-user", "synthetic-token"))
    monkeypatch.setattr(cli, "_create_cloud_adapter", lambda *args: DisconnectedAdapter())

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_doctor(SimpleNamespace())

    assert exc_info.value.code == 1
    assert closed == [True]
    assert "连接状态： ❌" in capsys.readouterr().out

def test_health_check_honors_timeout_and_closes_adapter():
    class SlowAdapter:
        closed = False

        async def connect(self):
            await asyncio.sleep(60)
            return True

        async def close(self):
            self.closed = True

    adapter = SlowAdapter()

    with pytest.raises(TimeoutError):
        asyncio.run(cli._check_adapter_health(adapter, timeout_seconds=0.001))

    assert adapter.closed is True


def test_health_check_closes_adapter_when_connect_raises():
    class FailingAdapter:
        closed = False

        async def connect(self):
            raise RuntimeError("synthetic connection failure")

        async def close(self):
            self.closed = True

    adapter = FailingAdapter()

    with pytest.raises(RuntimeError, match="synthetic connection failure"):
        asyncio.run(cli._check_adapter_health(adapter))

    assert adapter.closed is True


def test_sync_closes_adapter_when_connection_fails(monkeypatch, tmp_path):
    instances = []

    class DisconnectedAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            instances.append(self)

        async def connect(self):
            return False

        async def close(self):
            self.closed = True

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(
            mode="mi_fitness_cloud",
            region="cn",
            database_path=tmp_path / "mi_fitness.db",
        ),
    )
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: ("synthetic-user", "synthetic-token"))
    monkeypatch.setattr(cli, "MiFitnessCloudAdapter", DisconnectedAdapter)

    args = SimpleNamespace(type=None, start_date=None, end_date=None)
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cli.cmd_sync_async(args))

    assert exc_info.value.code == 1
    assert instances[0].closed is True



def test_sync_applies_configured_chunking_timeout_and_error_status(
    monkeypatch, tmp_path, capsys
):
    captured: dict[str, object] = {}
    timeouts: list[float] = []

    class ConnectedAdapter:
        async def connect(self):
            return True

        def get_available_data_types(self):
            return ["daily_activity"]

        async def close(self):
            captured["closed"] = True

    class FakeSyncService:
        def __init__(self, adapter, db, default_lookback_days, chunk_days):
            captured["adapter"] = adapter
            captured["lookback_days"] = default_lookback_days
            captured["chunk_days"] = chunk_days

        async def sync_data_type(self, **kwargs):
            captured["sync_kwargs"] = kwargs
            return {
                "status": "error",
                "added": 0,
                "updated": 0,
                "skipped": 0,
                "error": "synthetic sync failure",
            }

    config = Config(
        mode="mi_fitness_cloud",
        database_path=tmp_path / "mi_fitness.db",
        default_lookback_days=45,
        sync_chunk_days=5,
        sync_type_timeout_seconds=7.5,
    )
    real_wait_for = asyncio.wait_for

    async def recording_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: ("synthetic-user", "synthetic-token"))
    monkeypatch.setattr(cli, "_create_cloud_adapter", lambda *args: ConnectedAdapter())
    monkeypatch.setattr(cli, "SyncService", FakeSyncService)
    monkeypatch.setattr(cli.asyncio, "wait_for", recording_wait_for)

    args = SimpleNamespace(type="daily_activity", start_date=None, end_date=None)
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cli.cmd_sync_async(args))

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert captured["lookback_days"] == 45
    assert captured["chunk_days"] == 5
    assert captured["closed"] is True
    assert timeouts == [7.5]
    assert "status=error" in output
    assert "\u2705 daily_activity" not in output


def test_doctor_warns_on_non_default_db_path(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "get_config_path", lambda: config_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(mode="mi_fitness_cloud", database_path=tmp_path / "custom.db"),
    )
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: (None, None))
    monkeypatch.delenv("MI_FITNESS_DB_PATH", raising=False)

    with pytest.raises(SystemExit):
        cli.cmd_doctor(SimpleNamespace(db=str(tmp_path / "custom.db")))

    output = capsys.readouterr().out
    assert "非默认数据库路径" in output
    assert "icacls" in output


def test_doctor_quiet_on_default_db_path(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "get_config_path", lambda: config_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(mode="mi_fitness_cloud", database_path=tmp_path / "mi_fitness.db"),
    )
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: (None, None))
    monkeypatch.delenv("MI_FITNESS_DB_PATH", raising=False)

    with pytest.raises(SystemExit):
        cli.cmd_doctor(SimpleNamespace())

    assert "非默认数据库路径" not in capsys.readouterr().out
