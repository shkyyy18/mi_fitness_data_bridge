"""MCP server implementation for Mi Fitness."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.auth import load_mi_fitness_token, mask_account_id
from mi_fitness_mcp.config import load_config
from mi_fitness_mcp.models import ConnectionStatus, QueryResponse
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

logger = logging.getLogger(__name__)

app = Server(
    "mi-fitness-mcp",
    instructions=(
        "Unofficial, experimental, local-stdio Mi Fitness data bridge. "
        "Health results are sensitive and may leave the computer through the MCP client/model; "
        "do not publish them or request credentials in chat/tool arguments. Configure credentials "
        "only through the local interactive CLI. Inspect get_data_coverage before cache queries; "
        "use get_connection_status only when a cloud check is needed. sync_data contacts Xiaomi "
        "and writes local records: obtain user consent before syncing. Query tools do not refresh "
        "data automatically. Outputs are JSON text; inspect status/error and data_quality, "
        "and never interpret missing records as normal health or zero measurements. "
        "Dates are inclusive YYYY-MM-DD; prefer narrow ranges and small sample limits. "
        "Use query_workouts then workout_series for an activity curve, query_metric_series for "
        "daily activity/weight trends, and the specific query tools for raw samples. "
        "This is data access infrastructure, not medical advice."
    ),
)

config = None
db = None
adapter = None
sync_service = None
query_service = None
sync_tasks: dict[str, dict[str, Any]] = {}
sync_active = False
MAX_SYNC_TASKS = 100


def _prune_sync_tasks() -> None:
    completed = [
        sync_id
        for sync_id, state in sync_tasks.items()
        if state.get("status") not in {"queued", "running"}
    ]
    excess = max(0, len(sync_tasks) - MAX_SYNC_TASKS + 1)
    for sync_id in completed[:excess]:
        sync_tasks.pop(sync_id, None)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_connection_status",
            description=(
                "Check whether the configured Mi Fitness account can connect before requesting a "
                "sync. May contact Xiaomi, authenticate and rotate credentials in the local keyring; "
                "does not sync health records. Requires local interactive CLI setup, never "
                "credentials in tool arguments. Returns connected, mode, last_sync_at and "
                "available_data_types; configured responses also include connection_state, region, "
                "last_connection_error and sync_in_progress. While syncing, reports existing "
                "connection state instead of probing. For cached date coverage use get_data_coverage."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        ),
        Tool(
            name="sync_data",
            description=(
                "Download selected Mi Fitness datasets from Xiaomi into local SQLite; writes records "
                "and sync watermarks, may authenticate/rotate local credentials, and does not modify "
                "cloud health records. Requires local CLI setup and user authorization to access the "
                "account. Omitted data_types selects all adapter-supported types; an empty list is "
                "invalid. Dates are inclusive YYYY-MM-DD; start_date must not exceed end_date. "
                "Omitted end_date uses today; omitted start_date resumes the watermark or uses "
                "configured lookback (default 30 days). force_full_sync ignores the watermark, not "
                "the requested date range, and does not erase the database. Only one sync runs at a "
                "time. background=false waits for status ok/partial/error, sync_id, record counts and "
                "per-type results; background=true returns accepted plus sync_id to poll with "
                "get_sync_status. Partial results may already be stored; inspect results before "
                "retrying. Use cached query tools instead when no refresh is needed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "daily_activity",
                                "heart_rate",
                                "body_measurements",
                                "sleep",
                                "workouts",
                                "spo2",
                                "stress",
                                "abnormal_heart_beat",
                            ],
                        },
                        "description": "Dataset names; omitted selects all "
                        "adapter-supported datasets; [] is "
                        "invalid.",
                        "minItems": 1,
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion. "
                        "Omitted: saved watermark, or configured "
                        "lookback (default 30 days) if no "
                        "watermark/force_full_sync=true.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date. Omitted: "
                        "server local today.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "force_full_sync": {
                        "type": "boolean",
                        "description": "Ignore saved sync watermark and "
                        "re-fetch the requested range; no "
                        "deletion. If start_date is omitted "
                        "use configured lookback.",
                        "default": False,
                    },
                    "background": {
                        "type": "boolean",
                        "default": False,
                        "description": "False waits for results; true starts a "
                        "process-local task and returns sync_id "
                        "for get_sync_status polling.",
                    },
                },
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        ),
        Tool(
            name="get_sync_status",
            description=(
                "Poll an existing background sync using the exact sync_id returned by "
                "sync_data(background=true). Read-only in-memory lookup; no cloud request or new "
                "sync. Returns queued/running with timestamps, then the sync result "
                "(ok/partial/error, counts and per-type results), or cancelled. Unknown, pruned or "
                "pre-restart IDs return status=error; task history is process-local and bounded. This "
                "is job progress, not cloud connectivity (get_connection_status) or stored date "
                "coverage (get_data_coverage)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sync_id": {
                        "type": "string",
                        "description": "Opaque ID returned by sync_data with "
                        "background=true in this running server "
                        "process; not a workout ID.",
                        "minLength": 1,
                    }
                },
                "required": ["sync_id"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="get_profile",
            description=(
                "Read minimal metadata for the already-connected local account, not a medical or "
                "demographic profile. No cloud request or cache write; returns JSON text with status, "
                "source and data.profile containing account_id_masked, configured timezone and "
                "devices (currently an empty placeholder). Never returns credentials or plaintext "
                "account IDs. Returns status=error if disconnected; get_connection_status can "
                "establish/check the connection first. Use get_daily_summary for activity totals."
            ),
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="get_daily_summary",
            description=(
                "Read daily activity totals: steps, distance_m, active_kcal, total_kcal, floors and "
                "active_minutes, plus data_quality. Supply date for one day or both "
                "start_date/end_date for an inclusive YYYY-MM-DD range; date takes precedence if both "
                "forms are given. Returns data.summaries and data.data_quality. Missing optional "
                "upstream metrics may appear as zero with quality warnings; do not treat them as "
                "confirmed measurements. For one metric across days/weeks/months use "
                "query_metric_series; sleep and workouts have separate tools. Read-only local SQLite "
                "query; no cloud request or automatic sync. Requires a configured local "
                "account/cache. Returns JSON text with status, source=cache, generated_at and data; "
                "empty lists mean no cached matches, not zero measurements. Use get_data_coverage to "
                "inspect availability or sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Single calendar date YYYY-MM-DD, inclusive; "
                        "overrides start_date and end_date when "
                        "supplied.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                },
                "additionalProperties": False,
                "anyOf": [{"required": ["date"]}, {"required": ["start_date", "end_date"]}],
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_metric_series",
            description=(
                "Build a dated trend for steps (count), distance_m (meters), active_kcal (kcal), or "
                "weight_kg (kg) over an inclusive YYYY-MM-DD range. Returns data.metric and "
                "data.series [{date, value}], sorted ascending, without filling missing dates. "
                "Activity uses daily totals; weight uses the latest stored measurement per day. "
                "granularity=day returns these daily values; week groups from Monday, month from the "
                "first day. aggregation (default sum) applies only to week/month daily values; latest "
                "selects the last available day. Prefer avg or latest for weight. For raw body "
                "readings use query_body_measurements; heart-rate samples use query_heart_rate; one "
                "workout uses workout_series. Read-only local SQLite query; no cloud request or "
                "automatic sync. Requires a configured local account/cache. Returns JSON text with "
                "status, source=cache, generated_at and data; empty lists mean no cached matches, not "
                "zero measurements. Use get_data_coverage to inspect availability or sync_data to "
                "refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": ["steps", "distance_m", "active_kcal", "weight_kg"],
                        "description": "Metric and output units: steps=count, "
                        "distance_m=meters, active_kcal=kcal, "
                        "weight_kg=kg.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "description": "day returns daily values; week groups "
                        "by Monday; month by first day. Missing "
                        "days are not zero-filled.",
                        "default": "day",
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["sum", "avg", "min", "max", "latest"],
                        "description": "Reducer over daily values in "
                        "week/month buckets; ignored for day. "
                        "latest means last available date; avg "
                        "excludes missing days. Prefer "
                        "avg/latest for weight.",
                        "default": "sum",
                    },
                },
                "required": ["metric", "start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_heart_rate",
            description=(
                "Read timestamped heart-rate samples in bpm over an inclusive YYYY-MM-DD range, "
                "optionally filtering sample_type. Returns data.samples [{timestamp, bpm, "
                "sample_type}] and data.count, earliest first. limit defaults to 5000; use a smaller "
                "limit/date window for large datasets, with no pagination cursor. The cloud adapter "
                "normally stores resting/active/passive, so sample_type=workout may be empty; use "
                "workout_series with a workout_id to analyze all samples in that activity window. Not "
                "a diagnosis. Read-only local SQLite query; no cloud request or automatic sync. "
                "Requires a configured local account/cache. Returns JSON text with status, "
                "source=cache, generated_at and data; empty lists mean no cached matches, not zero "
                "measurements. Use get_data_coverage to inspect availability or sync_data to refresh "
                "with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "sample_type": {
                        "type": "string",
                        "enum": ["resting", "active", "passive", "workout"],
                        "description": "Optional exact stored sample type; "
                        "omit for all. Cloud records normally "
                        "use resting/active/passive; for "
                        "workout-window samples use "
                        "workout_series.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum earliest matching records to return "
                        "(default 5000); use a small positive value "
                        "to limit context. No offset/cursor is "
                        "available.",
                        "default": 5000,
                        "minimum": 1,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_body_measurements",
            description=(
                "Read timestamped body measurements over an inclusive YYYY-MM-DD range. Returns "
                "data.measurements and data.count in timestamp order; latest_only=true returns only "
                "the last matching record, not the latest value of each field. Omitted/empty metrics "
                "returns all available fields; otherwise timestamp plus selected fields, with absent "
                "optional measurements omitted. Units are kg for mass, percent for body fat/water, "
                "dimensionless for BMI. Use query_metric_series(metric=weight_kg) for a daily or "
                "aggregated weight trend. No pagination; narrow the date range. Read-only local "
                "SQLite query; no cloud request or automatic sync. Requires a configured local "
                "account/cache. Returns JSON text with status, source=cache, generated_at and data; "
                "empty lists mean no cached matches, not zero measurements. Use get_data_coverage to "
                "inspect availability or sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "weight_kg",
                                "bmi",
                                "body_fat_pct",
                                "muscle_mass_kg",
                                "water_pct",
                            ],
                        },
                        "description": "Optional body-field projection; timestamp "
                        "always remains. Omit or [] for all "
                        "available fields. Missing optional fields "
                        "are omitted, not zero.",
                    },
                    "latest_only": {
                        "type": "boolean",
                        "description": "Return only the last measurement in "
                        "this range when true; false returns "
                        "all matching records.",
                        "default": False,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_sleep",
            description=(
                "Read sleep sessions (start-date filtered) and a main-sleep summary (local wake-date "
                "filtered) over an inclusive YYYY-MM-DD range. Returns data.sessions, count, "
                "main_sessions, metrics and data_quality; main sleep is the longest valid non-nap per wake date. "
                "include_naps defaults true and affects the raw list only, not main-sleep selection. "
                "Times include start_at/end_at; durations are minutes; sleep_score/source can be null "
                "and missing scores are not zero. Expand dates around midnight if needed; raw counts "
                "can differ from wake-date summary counts. Use this instead of get_daily_summary for "
                "sleep. No pagination; narrow the date range. Read-only local SQLite query; no cloud "
                "request or automatic sync. Requires a configured local account/cache. Returns JSON "
                "text with status, source=cache, generated_at and data; empty lists mean no cached "
                "matches, not zero measurements. Use get_data_coverage to inspect availability or "
                "sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "include_naps": {
                        "type": "boolean",
                        "description": "Include naps in raw sessions (default "
                        "true); main-sleep summary always "
                        "excludes naps.",
                        "default": True,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_workouts",
            description=(
                "List recorded workouts starting within an inclusive YYYY-MM-DD range. Returns "
                "data.workouts, count and data_quality; rows include workout_id, activity_type, "
                "start_at/end_at, duration_minutes, distance_m, calories_kcal and available "
                "heart-rate/pace fields (missing fields may be null). activity_types matches "
                "case-insensitively; min_duration is minutes and min_distance_km is kilometers "
                "(unlike output distance_m). Filters combine with AND. No pagination; narrow dates. "
                "Use a returned workout_id with workout_series for a heart-rate curve; this tool "
                "returns session summaries, not samples. Read-only local SQLite query; no cloud "
                "request or automatic sync. Requires a configured local account/cache. Returns JSON "
                "text with status, source=cache, generated_at and data; empty lists mean no cached "
                "matches, not zero measurements. Use get_data_coverage to inspect availability or "
                "sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "activity_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional activity labels from "
                        "stored workouts (e.g. running); "
                        "case-insensitive. Omit or [] for "
                        "all; labels depend on "
                        "device/upstream data.",
                    },
                    "min_duration": {
                        "type": "integer",
                        "description": "Minimum workout duration in minutes, "
                        "inclusive; 0 or omitted disables this "
                        "filter.",
                        "minimum": 0,
                    },
                    "min_distance_km": {
                        "type": "number",
                        "description": "Minimum workout distance in "
                        "kilometers, inclusive; 0 or "
                        "omitted disables this filter. "
                        "Returned distance uses meters.",
                        "minimum": 0,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="workout_series",
            description=(
                "Read an auto-downsampled heart-rate curve for one workout_id obtained from "
                "query_workouts (contract agent-safe-series/v1). Uses all cached heart-rate sample "
                "types inside the workout window. Returns data with numeric t offsets in seconds from "
                "start_time, bpm values, downsampled/source_points/returned_points/method and "
                "full-resolution summary statistics. resolution defaults to 60 seconds and increases "
                "to respect max_points (default 400, hard cap 500). Pass the same reference_max_hr in "
                "bpm for comparable time_in_zone across activities; otherwise each workout uses its "
                "own maximum, so zones are not comparable. Unknown workout IDs or unsupported metrics "
                "return status=error. For raw date-range samples use query_heart_rate. Read-only "
                "local SQLite query; no cloud request or automatic sync. Requires a configured local "
                "account/cache. Returns JSON text with status, source=cache, generated_at and data; "
                "empty lists mean no cached matches, not zero measurements. Use get_data_coverage to "
                "inspect availability or sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workout_id": {
                        "type": "string",
                        "description": "Exact workout_id returned by "
                        "query_workouts for this account; do not "
                        "invent an ID.",
                        "minLength": 1,
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["heart_rate"],
                        "default": "heart_rate",
                        "description": "Only heart_rate is supported; values are "
                        "beats per minute (bpm).",
                    },
                    "resolution": {
                        "type": "integer",
                        "default": 60,
                        "description": "Requested bucket duration in seconds "
                        "(default 60, at least 1); automatically "
                        "increased to fit max_points.",
                        "minimum": 1,
                    },
                    "max_points": {
                        "type": "integer",
                        "default": 400,
                        "maximum": 500,
                        "description": "Requested maximum returned points "
                        "(default 400, 1..500); server also "
                        "clamps direct service calls to this "
                        "range.",
                        "minimum": 1,
                    },
                    "reference_max_hr": {
                        "type": "integer",
                        "description": "Optional positive reference "
                        "maximum heart rate in bpm for "
                        "zone normalization; use the same "
                        "value across compared workouts. "
                        "Omit to use this workout maximum.",
                        "minimum": 1,
                    },
                },
                "required": ["workout_id"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_spo2",
            description=(
                "Read stored blood oxygen saturation samples (spo2_pct, percent) over an inclusive "
                "YYYY-MM-DD range. Returns data.samples [{timestamp, spo2_pct}] and data.count, "
                "earliest first. limit defaults to 5000; no pagination cursor, so narrow dates or "
                "request a smaller limit. These are device measurements, not a diagnosis; missing "
                "records do not indicate normal oxygen levels. Use query_heart_rate for bpm rather "
                "than oxygen saturation. Read-only local SQLite query; no cloud request or automatic "
                "sync. Requires a configured local account/cache. Returns JSON text with status, "
                "source=cache, generated_at and data; empty lists mean no cached matches, not zero "
                "measurements. Use get_data_coverage to inspect availability or sync_data to refresh "
                "with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum earliest matching records to return "
                        "(default 5000); use a small positive value "
                        "to limit context. No offset/cursor is "
                        "available.",
                        "default": 5000,
                        "minimum": 1,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_stress",
            description=(
                "Read device stress samples over an inclusive YYYY-MM-DD range, optionally filtered "
                "by level (low/medium/high). Returns data.samples [{timestamp, stress_score, level}] "
                "and data.count, earliest first. stress_score is the upstream device score, not a "
                "clinical assessment. limit defaults to 5000; no pagination cursor, so narrow dates "
                "or request a smaller limit. Use query_sleep for sleep quality rather than inferring "
                "it from stress. Read-only local SQLite query; no cloud request or automatic sync. "
                "Requires a configured local account/cache. Returns JSON text with status, "
                "source=cache, generated_at and data; empty lists mean no cached matches, not zero "
                "measurements. Use get_data_coverage to inspect availability or sync_data to refresh "
                "with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Optional exact stored stress level: low, "
                        "medium or high; omit to include all levels.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum earliest matching records to return "
                        "(default 5000); use a small positive value "
                        "to limit context. No offset/cursor is "
                        "available.",
                        "default": 5000,
                        "minimum": 1,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="query_abnormal_heart_beat",
            description=(
                "Read device-reported abnormal-heartbeat events starting within an inclusive "
                "YYYY-MM-DD range. Returns data.events [{event_id, start_at, end_at, "
                "duration_seconds}] and data.count, earliest first. limit defaults to 5000; no "
                "pagination cursor, so narrow dates or request a smaller limit. Events are upstream "
                "flags, not a diagnosis; an empty list is not evidence of a healthy heart. Use "
                "query_heart_rate for ordinary bpm samples, not this event list. Read-only local "
                "SQLite query; no cloud request or automatic sync. Requires a configured local "
                "account/cache. Returns JSON text with status, source=cache, generated_at and data; "
                "empty lists mean no cached matches, not zero measurements. Use get_data_coverage to "
                "inspect availability or sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Inclusive first calendar date, "
                        "YYYY-MM-DD; must be on or before "
                        "end_date. Uses stored calendar dates, "
                        "not caller timezone conversion.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Inclusive last calendar date, YYYY-MM-DD; "
                        "must be on or after start_date.",
                        "format": "date",
                        "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                        "examples": ["2026-01-15"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum earliest matching records to return "
                        "(default 5000); use a small positive value "
                        "to limit context. No offset/cursor is "
                        "available.",
                        "default": 5000,
                        "minimum": 1,
                    },
                },
                "required": ["start_date", "end_date"],
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
        Tool(
            name="get_data_coverage",
            description=(
                "Inspect which date ranges already exist in the local cache before choosing query "
                "dates or requesting sync_data. Returns data.coverage [{data_type, first_date, "
                "last_date, days_with_data}] for nonempty datasets; omitted/empty data_types means "
                "all datasets. Empty datasets are omitted, and first/last dates do not guarantee "
                "uninterrupted coverage between them. This does not test cloud connectivity or report "
                "a background job; use get_connection_status or get_sync_status respectively. "
                "Read-only local SQLite query; no cloud request or automatic sync. Requires a "
                "configured local account/cache. Returns JSON text with status, source=cache, "
                "generated_at and data; empty lists mean no cached matches, not zero measurements. "
                "Use sync_data to refresh with user consent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "daily_activity",
                                "heart_rate",
                                "body_measurements",
                                "sleep",
                                "workouts",
                                "spo2",
                                "stress",
                                "abnormal_heart_beat",
                            ],
                        },
                        "description": "Optional dataset names to inspect; omit "
                        "or [] for all cached datasets.",
                    }
                },
                "additionalProperties": False,
            },
            annotations={
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        ),
    ]


def _validate_date_arguments(name: str, arguments: dict[str, Any]) -> None:
    """Reject invalid/reversed dates before any cloud or database operation."""
    dates = {}
    for key in ("date", "start_date", "end_date"):
        if key not in arguments:
            continue
        value = arguments[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} must use YYYY-MM-DD format")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{key} must be a valid YYYY-MM-DD date") from exc
        if parsed.date().isoformat() != value:
            raise ValueError(f"{key} must use YYYY-MM-DD format")
        dates[key] = parsed
    # The documented single-day shortcut takes precedence over a valid range.
    if name == "get_daily_summary" and "date" in dates:
        return
    if "start_date" in dates and "end_date" in dates and dates["start_date"] > dates["end_date"]:
        raise ValueError("start_date must not be after end_date")


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        _validate_date_arguments(name, arguments)
        if name == "get_connection_status":
            result = await _handle_get_connection_status()
        elif name == "sync_data":
            result = await _handle_sync_data(arguments)
        elif name == "get_sync_status":
            result = _handle_get_sync_status(arguments)
        elif name == "get_profile":
            result = await _handle_get_profile()
        elif name == "get_daily_summary":
            result = await _handle_get_daily_summary(arguments)
        elif name == "query_metric_series":
            result = await _handle_query_metric_series(arguments)
        elif name == "query_heart_rate":
            result = await _handle_query_heart_rate(arguments)
        elif name == "query_body_measurements":
            result = await _handle_query_body_measurements(arguments)
        elif name == "query_sleep":
            result = await _handle_query_sleep(arguments)
        elif name == "query_workouts":
            result = await _handle_query_workouts(arguments)
        elif name == "workout_series":
            result = await _handle_workout_series(arguments)
        elif name == "query_spo2":
            result = await _handle_query_spo2(arguments)
        elif name == "query_stress":
            result = await _handle_query_stress(arguments)
        elif name == "query_abnormal_heart_beat":
            result = await _handle_query_abnormal_heart_beat(arguments)
        elif name == "get_data_coverage":
            result = await _handle_get_data_coverage(arguments)
        else:
            result = {"status": "error", "error": f"Unknown tool: {name}"}
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    except Exception as e:
        logger.exception("Mi Fitness tool error")
        return [TextContent(type="text", text=json.dumps({"status": "error", "error": str(e)}))]


async def _handle_get_connection_status() -> dict:
    global adapter, config
    if not config or config.mode == "not_configured":
        return ConnectionStatus(
            mode="not_configured", connected=False, message="Server not configured."
        ).model_dump()

    connected = False
    if adapter is not None:
        if sync_service and sync_service.sync_in_progress:
            connected = adapter.is_connected()
        else:
            try:
                connected = await asyncio.wait_for(
                    adapter.health_check(), timeout=config.health_check_timeout_seconds
                )
            except Exception as exc:
                logger.warning("Connection health check failed: %s", exc)
                connected = False
    last_sync = None
    available_types = []
    if db:
        for data_type in [
            "daily_activity",
            "heart_rate",
            "body_measurements",
            "sleep",
            "workouts",
            "spo2",
            "stress",
            "abnormal_heart_beat",
        ]:
            state = db.get_sync_state(data_type)
            if state and state.get("last_sync_at"):
                available_types.append(data_type)
                sync_time = datetime.fromisoformat(state["last_sync_at"])
                if last_sync is None or sync_time > last_sync:
                    last_sync = sync_time
    result = ConnectionStatus(
        mode=config.mode,
        connected=connected,
        last_sync_at=last_sync,
        available_data_types=(adapter.get_available_data_types() if connected else available_types),
        message=getattr(adapter, "last_error", None) if not connected else None,
    ).model_dump()
    result.update(
        {
            "connection_state": "connected" if connected else "disconnected",
            "region": config.region,
            "last_health_check_at": getattr(adapter, "last_health_check_at", None),
            "last_connection_error": getattr(adapter, "last_error", None),
            "sync_in_progress": bool(sync_service and sync_service.sync_in_progress),
        }
    )
    return result


async def _background_sync(sync_id: str, arguments: dict) -> None:
    global sync_active
    try:
        sync_tasks[sync_id].update(status="running", started_at=datetime.now(UTC).isoformat())
        sync_tasks[sync_id] = await _run_sync_data(arguments, sync_id)
    except asyncio.CancelledError:
        sync_tasks[sync_id] = {"sync_id": sync_id, "status": "cancelled"}
        raise
    except Exception as exc:
        logger.exception("Background synchronization failed")
        sync_tasks[sync_id] = {
            "sync_id": sync_id,
            "status": "error",
            "error_code": type(exc).__name__,
            "error": str(exc),
        }
    finally:
        sync_active = False


async def _handle_sync_data(arguments: dict) -> dict:
    global sync_active
    # No await between check and assignment: foreground/background reservation is atomic.
    if sync_active:
        return {"status": "error", "error": "Another synchronization is in progress"}
    sync_active = True

    if arguments.get("background"):
        try:
            _prune_sync_tasks()
            sync_id = str(uuid.uuid4())
            sync_tasks[sync_id] = {
                "sync_id": sync_id,
                "status": "queued",
                "created_at": datetime.now(UTC).isoformat(),
            }
            task = asyncio.create_task(
                _background_sync(sync_id, {**arguments, "background": False})
            )
            sync_tasks[sync_id]["task"] = task
            return {"status": "accepted", "sync_id": sync_id}
        except Exception:
            sync_active = False
            raise

    try:
        return await _run_sync_data(arguments)
    finally:
        sync_active = False


def _handle_get_sync_status(arguments: dict) -> dict:
    state = sync_tasks.get(arguments.get("sync_id"))
    if state is None:
        return {"status": "error", "error": "Unknown sync_id"}
    return {key: value for key, value in state.items() if key != "task"}


async def _run_sync_data(arguments: dict, sync_id: str | None = None) -> dict:

    if not sync_service:
        return {"status": "error", "error": "Sync service not initialized"}
    if (not adapter or not adapter.is_connected()) and (not adapter or not await adapter.connect()):
        return {"status": "error", "error": getattr(adapter, "last_error", "Not connected")}
    data_types_arg = arguments.get("data_types")
    if data_types_arg == []:
        return {"status": "error", "error": "data_types must not be empty"}
    data_types = data_types_arg or sync_service.adapter.get_available_data_types()
    supported = set(sync_service.adapter.get_available_data_types())
    unknown = sorted(set(data_types) - supported)
    if unknown:
        return {"status": "error", "error": f"Unsupported data types: {', '.join(unknown)}"}
    sync_id = sync_id or str(uuid.uuid4())
    started_at = datetime.now(UTC)
    totals = {"added": 0, "updated": 0, "skipped": 0}
    details = []
    for data_type in data_types:
        type_started = datetime.now(UTC)
        try:
            result = await asyncio.wait_for(
                sync_service.sync_data_type(
                    data_type=data_type,
                    start_date=arguments.get("start_date"),
                    end_date=arguments.get("end_date"),
                    force_full=arguments.get("force_full_sync", False),
                ),
                timeout=config.sync_type_timeout_seconds,
            )
            result_status = result.get("status", "ok")
            for key in totals:
                totals[key] += result.get(key, 0)
            details.append(
                {
                    "data_type": data_type,
                    "status": result_status,
                    **result,
                    "duration_seconds": (datetime.now(UTC) - type_started).total_seconds(),
                }
            )
        except TimeoutError:
            details.append(
                {
                    "data_type": data_type,
                    "status": "error",
                    "error_code": "timeout",
                    "error": "Data type synchronization timed out",
                }
            )
        except Exception as exc:
            logger.exception("Failed to sync %s", data_type)
            details.append(
                {
                    "data_type": data_type,
                    "status": "error",
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                }
            )
    succeeded = [item["data_type"] for item in details if item["status"] == "ok"]
    has_partial = any(item["status"] == "partial" for item in details)
    status = (
        "ok"
        if len(succeeded) == len(details)
        else "partial"
        if succeeded or has_partial
        else "error"
    )
    return {
        "status": status,
        "sync_id": sync_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "records_added": totals["added"],
        "records_updated": totals["updated"],
        "records_skipped": totals["skipped"],
        "data_types_synced": succeeded,
        "results": details,
    }


async def _handle_get_profile() -> dict:
    if not adapter or not adapter.is_connected():
        return {"status": "error", "error": "Not connected to data source"}
    return QueryResponse(
        status="ok",
        source=config.mode if config else "unknown",
        data={
            "profile": {
                # 不向模型返回明文 user_id, 只给掩码形式（与 CLI 共用同一掩码函数）。
                "account_id_masked": mask_account_id(adapter.get_user_id()),
                "timezone": config.timezone if config else "UTC",
                "devices": [],
            }
        },
    ).model_dump()


async def _handle_get_daily_summary(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    start_date = arguments.get("date") or arguments.get("start_date")
    end_date = arguments.get("date") or arguments.get("end_date")
    if not start_date or not end_date:
        return {"status": "error", "error": "date or start_date/end_date required"}
    summaries = query_service.get_daily_summaries(start_date, end_date)
    missing = [
        metric
        for metric in ("total_kcal", "floors", "active_minutes")
        if summaries and all(not summary.get(metric) for summary in summaries)
    ]
    return QueryResponse(
        status="ok",
        source="cache",
        data={
            "summaries": summaries,
            "data_quality": query_service.get_data_quality("daily_activity", missing),
        },
    ).model_dump()


async def _handle_query_metric_series(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    series = query_service.get_metric_series(
        metric=arguments["metric"],
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        granularity=arguments.get("granularity", "day"),
        aggregation=arguments.get("aggregation", "sum"),
    )
    return QueryResponse(
        status="ok", source="cache", data={"metric": arguments["metric"], "series": series}
    ).model_dump()


async def _handle_query_heart_rate(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    samples = query_service.get_heart_rate_samples(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        sample_type=arguments.get("sample_type"),
        limit=arguments.get("limit"),
    )
    return QueryResponse(
        status="ok", source="cache", data={"samples": samples, "count": len(samples)}
    ).model_dump()


async def _handle_query_body_measurements(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    measurements = query_service.get_body_measurements(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        metrics=arguments.get("metrics"),
    )
    if arguments.get("latest_only") and measurements:
        measurements = [measurements[-1]]
    return QueryResponse(
        status="ok", source="cache", data={"measurements": measurements, "count": len(measurements)}
    ).model_dump()


async def _handle_query_sleep(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    sessions = query_service.get_sleep_sessions(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        include_naps=arguments.get("include_naps", True),
    )
    summary = query_service.get_sleep_summary(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
    )
    return QueryResponse(
        status="ok",
        source="cache",
        data={"sessions": sessions, "count": len(sessions), **summary},
    ).model_dump()


async def _handle_query_workouts(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    workouts = query_service.get_workouts(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        activity_types=arguments.get("activity_types"),
        min_duration=arguments.get("min_duration"),
        min_distance_km=arguments.get("min_distance_km"),
    )
    missing = [
        metric
        for metric in ("avg_heart_rate_bpm", "distance_m", "calories_kcal")
        if workouts and all(workout.get(metric) is None for workout in workouts)
    ]
    return QueryResponse(
        status="ok",
        source="cache",
        data={
            "workouts": workouts,
            "count": len(workouts),
            "data_quality": query_service.get_data_quality("workouts", missing),
        },
    ).model_dump()


async def _handle_workout_series(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    try:
        series = query_service.get_workout_series(
            workout_id=arguments["workout_id"],
            metric=arguments.get("metric", "heart_rate"),
            resolution=arguments.get("resolution", 60),
            max_points=arguments.get("max_points", 400),
            reference_max_hr=arguments.get("reference_max_hr"),
        )
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    return QueryResponse(status="ok", source="cache", data=series).model_dump()


async def _handle_query_spo2(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    samples = query_service.get_spo2_samples(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        limit=arguments.get("limit"),
    )
    return QueryResponse(
        status="ok", source="cache", data={"samples": samples, "count": len(samples)}
    ).model_dump()


async def _handle_query_stress(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    samples = query_service.get_stress_samples(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        level=arguments.get("level"),
        limit=arguments.get("limit"),
    )
    return QueryResponse(
        status="ok", source="cache", data={"samples": samples, "count": len(samples)}
    ).model_dump()


async def _handle_query_abnormal_heart_beat(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    events = query_service.get_abnormal_heart_beat_events(
        start_date=arguments["start_date"],
        end_date=arguments["end_date"],
        limit=arguments.get("limit"),
    )
    return QueryResponse(
        status="ok", source="cache", data={"events": events, "count": len(events)}
    ).model_dump()


async def _handle_get_data_coverage(arguments: dict) -> dict:
    if not query_service:
        return {"status": "error", "error": "Query service not initialized"}
    coverage = query_service.get_data_coverage(arguments.get("data_types"))
    return QueryResponse(status="ok", source="cache", data={"coverage": coverage}).model_dump()


async def main(db_path=None):
    global config, db, adapter, sync_service, query_service
    config = load_config()
    if db_path is not None:
        # Explicit CLI/--env override: serve strictly uses the given database.
        config.database_path = Path(db_path)
    db = Database(config.database_path)
    if config.mode == "mi_fitness_cloud":
        user_id, pass_token = load_mi_fitness_token()
        if user_id and pass_token:
            adapter = MiFitnessCloudAdapter(
                user_id=user_id, pass_token=pass_token, region=config.region
            )
            adapter.http_timeout = config.http_timeout_seconds
            adapter.request_retries = config.request_retries
            adapter.max_pages = config.max_pages
            # Do not connect here: MCP stdio must become available even when Xiaomi
            # authentication or networking is slow. Status/sync tools connect on demand.
    if adapter:
        sync_service = SyncService(
            adapter, db, config.default_lookback_days, config.sync_chunk_days
        )
        query_service = QueryService(db, adapter.get_user_id() or "unknown")
    else:
        query_service = QueryService(db, "unknown")
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        pending = [
            state.get("task") for state in sync_tasks.values() if state.get("task") is not None
        ]
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if adapter:
            await adapter.close()
