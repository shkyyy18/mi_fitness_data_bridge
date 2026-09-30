"""MCP job lifecycle/journal regressions. Synthetic metadata; never cloud credentials."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mi_fitness_mcp import server
from mi_fitness_mcp.storage import Database
from mi_fitness_mcp.storage.sync_history import SyncHistory


@pytest.fixture
def journal(tmp_path, monkeypatch):
    history = SyncHistory(Database(tmp_path / "synthetic.db"), "synthetic-user")
    monkeypatch.setattr(server, "sync_history", history)
    monkeypatch.setattr(server, "sync_tasks", {})
    monkeypatch.setattr(server, "sync_active", False)
    monkeypatch.setattr(server, "active_sync_id", None)
    yield history
    history.close()


def state(sync_id="synthetic-job", status="ok", **extra):
    return {"sync_id": sync_id, "status": status, "created_at": "2026-01-01T00:00:00Z", **extra}


def test_persistent_scoped_and_redacted(journal):
    journal.save(
        state(
            error="DO-NOT-STORE",
            task="DO-NOT-STORE",
            results=[
                {
                    "data_type": "sleep",
                    "status": "error",
                    "error_code": "timeout",
                    "error": "DO-NOT-STORE",
                    "raw": "DO-NOT-STORE",
                    "added": 2,
                }
            ],
        )
    )
    restored = SyncHistory(Database(journal.db.db_path), "synthetic-user")
    result = restored.get("synthetic-job")
    assert result["results"][0]["error_code"] == "timeout"
    assert "DO-NOT-STORE" not in json.dumps(result)
    assert "task" not in result
    other = SyncHistory(journal.db, "other-synthetic-user")
    assert other.get("synthetic-job") is None
    assert other.query() == []
    other.save(state(status="error"))
    assert journal.get("synthetic-job")["status"] == "ok"


def test_retention_recovery_and_lock(journal, monkeypatch):
    monkeypatch.setattr("mi_fitness_mcp.storage.sync_history.MAX_HISTORY", 2)
    for i in range(4):
        journal.save(state(f"done-{i}"))
    journal.save(state("live", "running"))
    assert len(journal.query()) == 3  # two finished plus the active job
    journal.acquire()
    second = SyncHistory(journal.db, "synthetic-user")
    with pytest.raises(RuntimeError, match="Another MCP server"):
        second.acquire()
    journal.close()
    second.acquire()
    try:
        second.recover_interrupted()
        assert second.get("live")["status"] == "interrupted"
        assert len(second.query()) == 2
    finally:
        second.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("background", [False, True])
async def test_success_persists_and_releases_reservation(journal, monkeypatch, background):
    runner = AsyncMock(
        return_value={"status": "ok", "records_added": 3, "finished_at": "2026-01-01T00:01:00Z"}
    )
    monkeypatch.setattr(server, "_run_sync_data", runner)
    result = await server._handle_sync_data({"background": background})
    sync_id = result["sync_id"]
    if background:
        assert result["status"] == "accepted"
        await server.sync_tasks[sync_id]["task"]
    assert server.sync_active is False
    assert journal.get(sync_id)["status"] == "ok"
    assert journal.get(sync_id)["records_added"] == 3
    server.sync_tasks.clear()  # simulate losing the process-local state
    assert server._handle_get_sync_status({"sync_id": sync_id})["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_cancel_before_or_after_first_step(journal, monkeypatch, started):
    entered = asyncio.Event()

    async def run(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(server, "_run_sync_data", run)
    result = await server._handle_sync_data({"background": True})
    sync_id = result["sync_id"]
    if started:
        await entered.wait()
    rejected = await server._handle_sync_data({"background": False})
    assert rejected["status"] == "error"
    cancelled = await server._handle_cancel_sync({"sync_id": sync_id})
    assert cancelled["status"] == "cancelled"
    assert journal.get(sync_id)["status"] == "cancelled"
    assert server.sync_active is False
    assert await server._handle_cancel_sync({"sync_id": sync_id}) == cancelled
    assert (await server._handle_cancel_sync({"sync_id": "missing"}))["status"] == "error"


@pytest.mark.asyncio
async def test_exception_and_foreground_cancellation(journal, monkeypatch):
    monkeypatch.setattr(
        server, "_run_sync_data", AsyncMock(side_effect=ValueError("synthetic error"))
    )
    result = await server._handle_sync_data({})
    assert result["status"] == "error"
    assert result["error_code"] == "ValueError"
    assert server.sync_active is False
    monkeypatch.setattr(server, "_run_sync_data", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await server._handle_sync_data({})
    assert server.sync_active is False
    assert "cancelled" in {job["status"] for job in journal.query()}


@pytest.mark.asyncio
async def test_history_pagination(journal):
    for i in range(3):
        journal.save(state(f"job-{i}"))
    first = json.loads((await server.call_tool("query_sync_history", {"limit": 2}))[0].text)["data"]
    assert [job["sync_id"] for job in first["jobs"]] == ["job-2", "job-1"]
    assert first["pagination"]["next_offset"] == 2
    last = json.loads(
        (await server.call_tool("query_sync_history", {"limit": 2, "offset": 2}))[0].text
    )["data"]
    assert [job["sync_id"] for job in last["jobs"]] == ["job-0"]
    assert last["pagination"]["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["acquire", "recover", "save", "adapter_close"])
async def test_main_releases_resources_on_failure(journal, monkeypatch, failure):
    fake_adapter = Mock()
    fake_adapter.get_user_id.return_value = "synthetic-user"
    fake_adapter.close = AsyncMock()
    monkeypatch.setattr(server, "adapter", fake_adapter)
    monkeypatch.setattr(server, "sync_service", None)
    monkeypatch.setattr(server, "query_service", None)
    monkeypatch.setattr(server, "db", None)
    monkeypatch.setattr(server, "config", None)
    monkeypatch.setattr(server, "SyncHistory", lambda *args: journal)
    monkeypatch.setattr(
        server,
        "load_config",
        lambda: SimpleNamespace(
            mode="synthetic", database_path=journal.db.db_path,
            default_lookback_days=30, sync_chunk_days=7,
        ),
    )

    @asynccontextmanager
    async def streams():
        yield None, None

    async def run(*args):
        if failure == "save":
            server.sync_tasks["synthetic-job"] = state(status="queued")
            server.sync_active = True
            server.active_sync_id = "synthetic-job"

    monkeypatch.setattr(server, "stdio_server", streams)
    monkeypatch.setattr(server.app, "run", run)
    closed = Mock(wraps=journal.close)
    monkeypatch.setattr(journal, "close", closed)
    error = RuntimeError("synthetic failure")
    if failure == "adapter_close":
        fake_adapter.close.side_effect = error
    else:
        method = {"acquire": "acquire", "recover": "recover_interrupted", "save": "save"}[failure]
        monkeypatch.setattr(journal, method, Mock(side_effect=error))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await server.main()
    fake_adapter.close.assert_awaited_once()
    closed.assert_called_once()
    assert journal._lock_file is None
    assert server.sync_active is False
    # A fresh process can take the lock after failed startup/shutdown.
    fresh = SyncHistory(journal.db, "synthetic-user")
    fresh.acquire()
    fresh.close()
