"""Synthetic wire-level pagination and legacy-name compatibility."""

import json
from unittest.mock import AsyncMock

import pytest
from mcp import types

from mi_fitness_mcp import server
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database


async def wire(name, arguments):
    result = await server.app.request_handlers[types.CallToolRequest](
        types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name=name,
                arguments=arguments,
            ),
        )
    )
    return result.root


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,key",
    [
        ("query_daily_activity", "summaries"),
        ("get_daily_summary", "summaries"),
        ("query_metric_series", "series"),
        ("query_body_measurements", "measurements"),
        ("query_sleep", "sessions"),
        ("query_workouts", "workouts"),
    ],
)
async def test_sequence_pages_apply_after_filtering(name, key, monkeypatch):
    legacy = {value: key for key, value in server.TOOL_ALIASES.items()}.get(name, name)
    handler = AsyncMock(
        side_effect=lambda args: {
            "status": "ok",
            "source": "cache",
            "data": {key: list(range(5)), "count": 5},
        }
    )
    monkeypatch.setattr(server, f"_handle_{legacy}", handler)
    args = {"start_date": "2026-01-01", "end_date": "2026-01-31", "limit": 2}
    if name == "query_metric_series":
        args["metric"] = "steps"
    rows = []
    offset = 0
    while offset is not None:
        response = await wire(name, {**args, "offset": offset})
        assert response.isError is False
        data = json.loads(response.content[0].text)["data"]
        assert data["count"] == len(data[key])
        assert data["pagination"]["offset"] == offset
        rows.extend(data[key])
        offset = data["pagination"]["next_offset"]
    assert rows == list(range(5))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,table,timestamp,column,value",
    [
        ("query_heart_rate", "heart_rate_samples", "timestamp", "bpm", 65),
        ("query_spo2", "spo2_samples", "timestamp", "spo2_pct", 94),
        ("query_stress", "stress_samples", "timestamp", "stress_score", 20),
        (
            "query_abnormal_heart_beat",
            "abnormal_heart_beat_events",
            "start_at",
            "duration_seconds",
            5,
        ),
    ],
)
async def test_sql_pages_have_no_gaps_with_stable_order(
    name,
    table,
    timestamp,
    column,
    value,
    tmp_path,
    monkeypatch,
):
    db = Database(tmp_path / "synthetic.db")
    # Fixed, test-owned identifiers only. Equal times where the table permits them.
    with db._get_connection() as conn:
        for i in reversed(range(5)):
            stamp = f"2026-01-01T12:00:0{i}"
            extra = {}
            if table == "heart_rate_samples":
                stamp = f"2026-01-01T12:00:0{i // 2}"
                extra = {"sample_type": "passive" if i % 2 else "resting"}
            elif table == "stress_samples":
                extra = {"level": "low"}
            elif table == "abnormal_heart_beat_events":
                stamp = "2026-01-01T12:00:00"
                extra = {"event_id": f"event-{i}", "end_at": "2026-01-01T12:00:10"}
            record = {
                "id": f"id-{i}",
                "provider": "mi_fitness",
                "source_type": "cloud_session",
                "user_id": "synthetic-user",
                timestamp: stamp,
                column: value + i,
                **extra,
            }
            conn.execute(
                f"INSERT INTO {table} ({','.join(record)}) "
                f"VALUES ({','.join('?' for _ in record)})",
                list(record.values()),
            )
        conn.commit()
    monkeypatch.setattr(server, "query_service", QueryService(db, "synthetic-user"))
    monkeypatch.setattr(server, "adapter", None)
    rows = []
    for offset in (0, 2, 4, 6):
        response = await wire(
            name,
            {"start_date": "2026-01-01", "end_date": "2026-01-01", "limit": 2, "offset": offset},
        )
        assert response.isError is False
        payload = json.loads(response.content[0].text)
        assert payload["status"] == "ok", payload
        data = payload["data"]
        key = server.PAGE_KEYS[name]
        rows.extend(data[key])
        assert data["pagination"]["has_more"] is (offset < 4)
        assert data["count"] == len(data[key])
    assert [row[column] for row in rows] == [value + i for i in range(5)]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["workout_series", "query_workout_series"])
async def test_workout_legacy_alias_is_validated_and_dispatched(name, monkeypatch):
    handler = AsyncMock(return_value={"status": "ok", "data": {"points": []}})
    monkeypatch.setattr(server, "_handle_workout_series", handler)
    result = await wire(name, {"workout_id": "synthetic-workout"})
    assert result.isError is False
    handler.assert_awaited_once()
    handler.reset_mock()
    result = await wire(name, {"workout_id": "synthetic-workout", "max_points": 0})
    assert result.isError is True
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["get_daily_summary", "query_daily_activity", "query_heart_rate"])
@pytest.mark.parametrize("bad", [{"offset": -1}, {"limit": 0}, {"limit": 5001}, {"offset": 1.5}])
async def test_invalid_page_rejected_before_dispatch(name, bad, monkeypatch):
    handler = AsyncMock(side_effect=AssertionError("must not dispatch"))
    legacy = "get_daily_summary" if name != "query_heart_rate" else name
    monkeypatch.setattr(server, f"_handle_{legacy}", handler)
    result = await wire(name, {"start_date": "2026-01-01", "end_date": "2026-01-02", **bad})
    assert result.isError is True
    handler.assert_not_called()
