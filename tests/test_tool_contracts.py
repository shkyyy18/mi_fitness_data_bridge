"""Public MCP contracts: synthetic data only, no setup/keyring/cloud access."""

import json
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator
from mcp import types

from mi_fitness_mcp import server
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database

DATE_RANGE = {"start_date": "2026-01-01", "end_date": "2026-01-31"}
EXAMPLES = {
    "get_connection_status": {},
    "sync_data": {"data_types": ["sleep"], **DATE_RANGE, "background": True},
    "get_sync_status": {"sync_id": "synthetic-job"},
    "get_profile": {},
    "get_daily_summary": {"date": "2026-01-15"},
    "query_metric_series": {"metric": "weight_kg", **DATE_RANGE},
    "query_heart_rate": {**DATE_RANGE, "limit": 10},
    "query_body_measurements": {**DATE_RANGE, "latest_only": True},
    "query_sleep": {**DATE_RANGE, "include_naps": False},
    "query_workouts": {**DATE_RANGE, "min_duration": 20},
    "workout_series": {"workout_id": "synthetic-workout", "max_points": 100},
    "query_spo2": {**DATE_RANGE, "limit": 10},
    "query_stress": {**DATE_RANGE, "level": "low"},
    "query_abnormal_heart_beat": DATE_RANGE,
    "get_data_coverage": {"data_types": ["sleep"]},
}


@pytest.mark.asyncio
async def test_wire_catalog_preserves_names_and_documents_every_parameter():
    result = await server.app.request_handlers[types.ListToolsRequest](
        types.ListToolsRequest(method="tools/list")
    )
    # Exercise actual SDK serialization, not just Python metadata constants.
    tools = json.loads(result.model_dump_json(by_alias=True))["tools"]
    assert {tool["name"] for tool in tools} == set(EXAMPLES)
    assert len(tools) == 15
    for tool in tools:
        name = tool["name"]
        schema = tool["inputSchema"]
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(EXAMPLES[name])
        assert len(tool["description"].split()) >= 35
        assert "return" in tool["description"].lower()
        assert schema["additionalProperties"] is False
        for prop in schema["properties"].values():
            assert len(prop["description"].split()) >= 5
            if "default" in prop:
                Draft202012Validator(prop).validate(prop["default"])
        annotations = tool["annotations"]
        cloud = name in {"sync_data", "get_connection_status"}
        assert annotations["openWorldHint"] is cloud
        assert annotations["readOnlyHint"] is (not cloud)
        assert annotations["destructiveHint"] is False
    assert "credentials" in server.app.instructions
    assert "consent" in server.app.instructions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_daily_summary", {}),
        ("get_daily_summary", {"start_date": "2026-01-01"}),
        ("query_heart_rate", {**DATE_RANGE, "limit": -1}),
        ("query_spo2", {**DATE_RANGE, "limit": 0}),
        ("query_stress", {**DATE_RANGE, "level": "invented"}),
        ("query_sleep", {**DATE_RANGE, "extra": True}),
        ("sync_data", {"data_types": []}),
        ("sync_data", {"data_types": ["invented"]}),
        ("workout_series", {"workout_id": "synthetic", "resolution": 0}),
        ("workout_series", {"workout_id": "synthetic", "max_points": 501}),
        ("workout_series", {"workout_id": "synthetic", "reference_max_hr": 0}),
        ("get_sync_status", {"sync_id": ""}),
        ("query_metric_series", {**DATE_RANGE, "metric": "invented"}),
    ],
)
async def test_sdk_rejects_invalid_arguments_before_dispatch(name, arguments, monkeypatch):
    handler = AsyncMock(side_effect=AssertionError("must not execute invalid input"))
    # The decorated function resolves global handlers only after SDK schema validation.
    local_name = "_handle_workout_series" if name == "workout_series" else f"_handle_{name}"
    monkeypatch.setattr(server, local_name, handler)
    result = await server.app.request_handlers[types.CallToolRequest](
        types.CallToolRequest(
            method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments)
        )
    )
    assert result.root.isError is True
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"start_date": "2026-02-30", "end_date": "2026-03-01"},
        {"start_date": "2026-1-01", "end_date": "2026-01-31"},
        {"start_date": "2026-02-01", "end_date": "2026-01-01"},
        {"start_date": None},
    ],
)
async def test_invalid_dates_do_not_start_cloud_sync(arguments, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(server, "_handle_sync_data", handler)
    result = json.loads((await server.call_tool("sync_data", arguments))[0].text)
    assert result["status"] == "error"
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_single_day_precedence_is_preserved(monkeypatch):
    handler = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(server, "_handle_get_daily_summary", handler)
    result = await server.call_tool(
        "get_daily_summary",
        {"date": "2026-01-15", "start_date": "2026-02-01", "end_date": "2026-01-01"},
    )
    assert json.loads(result[0].text)["status"] == "ok"
    handler.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "keys"),
    [
        ("get_daily_summary", {"summaries", "data_quality"}),
        ("query_metric_series", {"metric", "series"}),
        ("query_heart_rate", {"samples", "count"}),
        ("query_body_measurements", {"measurements", "count"}),
        ("query_sleep", {"sessions", "count", "main_sessions", "metrics", "data_quality"}),
        ("query_workouts", {"workouts", "count", "data_quality"}),
        ("query_spo2", {"samples", "count"}),
        ("query_stress", {"samples", "count"}),
        ("query_abnormal_heart_beat", {"events", "count"}),
        ("get_data_coverage", {"coverage"}),
    ],
)
async def test_cache_response_shapes_match_documentation(name, keys, tmp_path, monkeypatch):
    service = QueryService(Database(tmp_path / "synthetic.db"), "synthetic-contract-user")
    monkeypatch.setattr(server, "query_service", service)
    # No cloud adapter at all: cached queries must work without one.
    monkeypatch.setattr(server, "adapter", None)
    response = json.loads((await server.call_tool(name, EXAMPLES[name]))[0].text)
    assert response["status"] == "ok"
    assert response["source"] == "cache"
    assert set(response["data"]) == keys
