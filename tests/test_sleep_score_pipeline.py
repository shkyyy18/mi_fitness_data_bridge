"""Synthetic issue #14 investigation: scores across adapter/cache/MCP/export.

These tests verify the local pipeline, NOT availability on Xiaomi devices.
No account, keyring, existing database or live endpoint is accessed.
"""
from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, datetime

import pytest

from mi_fitness_mcp import server
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.export import export_database
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

DAY = "2026-01-10"
START = int(datetime(2026, 1, 10, 0, 0, tzinfo=UTC).timestamp())
USER = "synthetic-score-user"


def _adapter(monkeypatch, fields):
    adapter = MiFitnessCloudAdapter(user_id=USER, pass_token="synthetic-unused-token")
    adapter._connected = True
    adapter._client = object()

    async def fetch(key, start_date, end_date):
        assert (key, start_date, end_date) == ("sleep", DAY, DAY)
        return [{
            "time": START + 8 * 3600,
            "sid": "synthetic-device",
            "zone_offset": 0,
            "value": json.dumps({
                "bedtime": START,
                "wake_up_time": START + 8 * 3600,
                "duration": 480,
                **fields,
            }),
        }]

    async def reports(start_date, end_date):
        return []

    monkeypatch.setattr(adapter, "_fetch_key", fetch)
    monkeypatch.setattr(adapter, "_fetch_daily_sleep_reports", reports)
    return adapter


@pytest.mark.parametrize(("fields", "expected"), [
    ({"score": 88}, 88),
    ({"sleep_score": 88}, 88),
    ({"sleep_score": "88"}, 88),
    ({"score": None, "sleep_score": 88}, 88),
    ({"score": "invalid", "sleep_score": 88}, 88),
    ({"score": "0", "sleep_score": 88}, 88),
    ({"score": 0}, None),
    ({"score": True}, None),
    ({"score": 101}, None),
    ({"score": -1}, None),
    ({"score": "nan"}, None),
    ({"score": "inf"}, None),
    ({"score": []}, None),
    ({"score": 88.5}, None),
    ({}, None),
    ({"score": None, "sleep_score": None}, None),
])
def test_sleep_score_survives_sync_mcp_json_csv(monkeypatch, tmp_path, fields, expected):
    adapter = _adapter(monkeypatch, fields)
    path = tmp_path / "synthetic.db"
    db = Database(path)
    result = asyncio.run(SyncService(adapter, db).sync_data_type("sleep", DAY, DAY))
    assert result["added"] == 1
    assert result["skipped"] == 0
    assert db.query_sleep_sessions(USER, DAY, DAY)[0]["sleep_score"] == expected

    monkeypatch.setattr(server, "query_service", QueryService(db, USER))
    response = asyncio.run(server._handle_query_sleep({"start_date": DAY, "end_date": DAY}))
    assert response["data"]["count"] == 1
    assert response["data"]["sessions"][0]["sleep_score"] == expected
    assert response["data"]["data_quality"]["sleep_score_days"] == int(expected is not None)

    target = tmp_path / "synthetic.json"
    export_database(path, target, output_format="json", dataset="sleep")
    exported = json.loads(target.read_text(encoding="utf-8"))
    assert exported["records"]["sleep"][0]["sleep_score"] == expected

    written = export_database(path, tmp_path / "csv", output_format="csv", dataset="sleep")
    with written[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["sleep_score"] == ("" if expected is None else str(expected))


def test_resync_updates_previously_missing_score(monkeypatch, tmp_path):
    fields = {}
    adapter = _adapter(monkeypatch, fields)
    db = Database(tmp_path / "synthetic.db")
    sync = SyncService(adapter, db)
    first = asyncio.run(sync.sync_data_type("sleep", DAY, DAY))
    assert first["added"] == 1
    assert db.query_sleep_sessions(USER, DAY, DAY)[0]["sleep_score"] is None

    # A later upstream response now includes a score; explicit-range re-sync
    # must update the cached record, not require deleting the user's database.
    fields["sleep_score"] = 88
    second = asyncio.run(sync.sync_data_type("sleep", DAY, DAY))
    assert second["added"] == 0
    assert second["updated"] == 1
    rows = db.query_sleep_sessions(USER, DAY, DAY)
    assert len(rows) == 1
    assert rows[0]["sleep_score"] == 88
