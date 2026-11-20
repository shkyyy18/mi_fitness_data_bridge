"""Synthetic CLI checks with a strict GBK output stream; no cloud or keyring I/O."""
import io
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

from mi_fitness_mcp import main as cli
from mi_fitness_mcp.config import Config


@pytest.fixture
def gbk_output():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="gbk", errors="strict", write_through=True)
    yield SimpleNamespace(stream=stream, getvalue=raw.getvalue)
    stream.detach()


def run_cli(output, command, args):
    with redirect_stdout(output.stream):
        command(args)


@pytest.fixture
def synthetic_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    config = Config(mode="mi_fitness_cloud", database_path=tmp_path / "synthetic.db")
    monkeypatch.setattr(cli, "get_config_path", lambda: config_path)
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "resolve_database_path", lambda override: None)
    monkeypatch.setattr(cli, "keyring_backend_warning", lambda: "synthetic backend warning")
    monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: ("synthetic-user", "synthetic-token"))
    return config


@pytest.mark.parametrize("connected", [True, False, None])
def test_doctor_gbk_preserves_result(monkeypatch, synthetic_config, gbk_output, connected):
    closed = []

    class Adapter:
        region = "cn"

        async def connect(self):
            return connected

        def get_available_data_types(self):
            return ["daily_activity"]

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(cli, "_create_cloud_adapter", lambda *args: Adapter())
    if connected is None:
        monkeypatch.setattr(cli, "load_mi_fitness_token", lambda: (None, None))
    if connected:
        run_cli(gbk_output, cli.cmd_doctor, SimpleNamespace())
    else:
        with pytest.raises(SystemExit) as exc:
            run_cli(gbk_output, cli.cmd_doctor, SimpleNamespace())
        assert exc.value.code == 1
    output = gbk_output.getvalue().decode("gbk")
    assert "配置已加载" in output
    assert "synthetic backend warning" in output
    assert "synthetic-token" not in output
    assert "数据库将在首次运行时创建" in output
    if connected is None:
        assert "未找到 Mi Fitness 凭据" in output
        assert closed == []
    else:
        assert "连接状态" in output
        assert closed == [True]


def test_setup_gbk_keeps_hidden_input_and_save(monkeypatch, gbk_output):
    answers = iter(["synthetic-user", "cn"])
    saved = []
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "synthetic-token")
    monkeypatch.setattr(cli, "save_mi_fitness_token", lambda *args: saved.append(args))
    monkeypatch.setattr(cli, "save_config", lambda config: None)
    monkeypatch.setattr(cli, "keyring_backend_warning", lambda: "synthetic backend warning")
    run_cli(gbk_output, cli.cmd_setup, SimpleNamespace())
    output = gbk_output.getvalue().decode("gbk")
    assert "配置已保存" in output
    assert "synthetic-token" not in output
    assert saved == [("synthetic-user", "synthetic-token")]


@pytest.mark.parametrize("status", ["ok", "partial", "failed"])
def test_sync_gbk_preserves_result_and_closes(monkeypatch, synthetic_config, gbk_output, status):
    closed = []

    class Adapter:
        async def connect(self):
            return True

        async def close(self):
            closed.append(True)

    class Service:
        async def sync_data_type(self, **kwargs):
            return {"status": status, "added": 0, "updated": 0, "error": "synthetic failure"}

    monkeypatch.setattr(cli, "Database", lambda path: object())
    monkeypatch.setattr(cli, "_create_cloud_adapter", lambda *args: Adapter())
    monkeypatch.setattr(cli, "SyncService", lambda *args, **kwargs: Service())
    args = SimpleNamespace(type="daily_activity", start_date=None, end_date=None)
    if status == "ok":
        run_cli(gbk_output, cli.cmd_sync, args)
    else:
        with pytest.raises(SystemExit) as exc:
            run_cli(gbk_output, cli.cmd_sync, args)
        assert exc.value.code == 1
    output = gbk_output.getvalue().decode("gbk")
    assert "daily_activity" in output
    assert closed == [True]
    if status == "ok":
        assert "同步完成" in output
    else:
        assert "status=" + status in output
