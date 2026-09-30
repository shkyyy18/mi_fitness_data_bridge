"""Phase 1 运动明细汇总字段：适配器解析、老库迁移与回读。

覆盖 docs/workout-detail-feasibility.md Phase 1：
- iter_workouts 从既有 get_sport_records_by_time 响应的 value 中解析
  补充汇总字段与 FDS 定位元数据（不发新请求、零新依赖）。
- 老库增量补列后可正常写入与查询。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.models import Workout
from mi_fitness_mcp.storage import Database

_FULL_PAYLOAD = {
    "sport_type": 1,
    "proto_type": 1,
    "version": 2,
    "time": 1789998701,
    "timezone": 32,
    "start_time": 1789998701,
    "end_time": 1790001471,
    "duration": 2770,
    "distance": 4858,
    "calories": 320,
    "avg_hrm": 163,
    "max_hrm": 194,
    "min_hrm": 121,
    "avg_pace": 570,
    "max_pace": 420,
    "min_pace": 700,
    "steps": 6300,
    "valid_duration": 2740,
    "avg_cadence": 168,
    "max_cadence": 182,
    "avg_stride": 105,
    "avg_speed": 2.9,
    "avg_height": 52.5,
    "max_height": 88.0,
    "min_height": 31.0,
    "rise_height": 45.0,
    "fall_height": 40.5,
    "total_climbing": 45.0,
    "vo2max": 47,
    "train_effect": 3.5,
    "anaerobic_train_effect": 1.2,
    "training_load": 210,
    "recovery_time": 38,
    "avg_spo2": 96,
}


def _sport_record(payload: dict) -> dict:
    return {
        "sid": "2198620807",
        "key": "outdoor_running",
        "time": 1789998701,
        "category": "running",
        "zone_offset": 28800,
        "zone_name": "GMT+08:00",
        "value": json.dumps(payload),
    }


def _connected_adapter(records: list[dict]) -> MiFitnessCloudAdapter:
    adapter = MiFitnessCloudAdapter(user_id="123456", pass_token="token")
    adapter._connected = True
    adapter._client = object()  # is_connected() only checks it is not None

    async def fake_fetch(start_date, end_date, region=None):
        return records

    adapter._fetch_sport_records_by_time = fake_fetch
    return adapter


def _collect_workouts(adapter: MiFitnessCloudAdapter) -> list[Workout]:
    async def collect():
        return [w async for w in adapter.iter_workouts("2026-09-21", "2026-09-22")]

    return asyncio.run(collect())


def test_iter_workouts_parses_summary_and_fds_metadata():
    adapter = _connected_adapter([_sport_record(_FULL_PAYLOAD)])
    workouts = _collect_workouts(adapter)

    assert len(workouts) == 1
    workout = workouts[0]
    assert workout.avg_heart_rate_bpm == 163
    assert workout.min_heart_rate_bpm == 121
    assert workout.valid_duration_seconds == 2740
    assert workout.avg_cadence == 168
    assert workout.max_cadence == 182
    assert workout.avg_stride == 105
    assert workout.avg_speed_mps == 2.9
    assert workout.min_pace_sec_per_km == 700.0
    assert workout.avg_height_m == 52.5
    assert workout.max_height_m == 88.0
    assert workout.min_height_m == 31.0
    assert workout.rise_height_m == 45.0
    assert workout.fall_height_m == 40.5
    assert workout.total_climbing_m == 45.0
    assert workout.vo2max == 47
    assert workout.train_effect == 3.5
    assert workout.anaerobic_train_effect == 1.2
    assert workout.training_load == 210
    assert workout.recovery_time == 38
    assert workout.avg_spo2_pct == 96
    # FDS 定位元数据：数据 ID 必须用 proto_type 与报告级 time。
    assert workout.fds_sid == "2198620807"
    assert workout.proto_type == 1
    assert workout.report_version == 2
    assert workout.report_time == 1789998701
    assert workout.tz_in_15min == 32


def test_iter_workouts_omits_absent_optional_fields():
    minimal = {
        "start_time": 1789998701,
        "end_time": 1790001471,
        "duration": 2770,
        "distance": 4858,
    }
    adapter = _connected_adapter([_sport_record(minimal)])
    workouts = _collect_workouts(adapter)

    assert len(workouts) == 1
    workout = workouts[0]
    assert workout.distance_m == 4858
    assert workout.avg_cadence is None
    assert workout.vo2max is None
    assert workout.rise_height_m is None
    assert workout.fds_sid == "2198620807"  # 信封级字段独立于 value
    assert workout.proto_type is None
    assert workout.report_time is None


_OLD_WORKOUTS_SCHEMA = """
CREATE TABLE workouts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_record_id TEXT,
    user_id TEXT NOT NULL,
    device_id TEXT,
    timezone TEXT DEFAULT 'UTC',
    collected_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    workout_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    start_at TIMESTAMP NOT NULL,
    end_at TIMESTAMP NOT NULL,
    duration_minutes INTEGER NOT NULL,
    distance_m REAL,
    calories_kcal REAL,
    avg_heart_rate_bpm INTEGER,
    max_heart_rate_bpm INTEGER,
    avg_pace_sec_per_km REAL,
    max_pace_sec_per_km REAL,
    total_steps INTEGER,
    UNIQUE(user_id, workout_id)
)
"""

_NEW_COLUMNS = (
    "min_heart_rate_bpm",
    "valid_duration_seconds",
    "avg_cadence",
    "max_cadence",
    "avg_stride",
    "avg_speed_mps",
    "min_pace_sec_per_km",
    "avg_height_m",
    "max_height_m",
    "min_height_m",
    "rise_height_m",
    "fall_height_m",
    "total_climbing_m",
    "vo2max",
    "train_effect",
    "anaerobic_train_effect",
    "training_load",
    "recovery_time",
    "avg_spo2_pct",
    "fds_sid",
    "proto_type",
    "report_version",
    "report_time",
    "tz_in_15min",
)


def _workout(**overrides) -> Workout:
    values = {
        "id": "w-1",
        "provider": "mi_fitness",
        "source_type": "cloud_session",
        "user_id": "u-1",
        "workout_id": "wo-1",
        "activity_type": "run",
        "start_at": datetime(2026, 7, 1, 6),
        "end_at": datetime(2026, 7, 1, 7),
        "duration_minutes": 60,
    }
    values.update(overrides)
    return Workout(**values)


def test_pre_phase1_database_is_migrated_and_round_trips(tmp_path):
    db_path = tmp_path / "old_cache.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(_OLD_WORKOUTS_SCHEMA)
        conn.commit()

    db = Database(db_path)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(workouts)")}
    assert not [name for name in _NEW_COLUMNS if name not in columns]

    assert db.insert_workout(
        _workout(
            avg_cadence=168,
            vo2max=47,
            rise_height_m=45.0,
            fds_sid="2198620807",
            proto_type=1,
            report_version=2,
            report_time=1789998701,
            tz_in_15min=32,
        )
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT avg_cadence, vo2max, rise_height_m, fds_sid, proto_type,"
            " report_version, report_time, tz_in_15min FROM workouts WHERE id = 'w-1'"
        ).fetchone()
    assert tuple(row) == (168, 47, 45.0, "2198620807", 1, 2, 1789998701, 32)


def test_query_workouts_returns_summary_fields(tmp_path):
    db = Database(tmp_path / "mi_fitness.db")
    db.insert_workout(
        _workout(
            user_id="synthetic-test-user",
            avg_cadence=168,
            max_cadence=182,
            rise_height_m=45.0,
            vo2max=47,
            training_load=210,
        )
    )
    from mi_fitness_mcp.services.query_service import QueryService

    service = QueryService(db, "synthetic-test-user")
    workouts = service.get_workouts("2026-07-01", "2026-07-02")

    assert len(workouts) == 1
    assert workouts[0]["avg_cadence"] == 168
    assert workouts[0]["max_cadence"] == 182
    assert workouts[0]["rise_height_m"] == 45.0
    assert workouts[0]["vo2max"] == 47
    assert workouts[0]["training_load"] == 210
    assert workouts[0]["recovery_time"] is None


def test_iter_workouts_keeps_legitimate_zero_values():
    """海拔 0 / 无氧训练效果 0 是合法测量值，不得折叠成 NULL（review #5）。"""
    payload = dict(_FULL_PAYLOAD, avg_height=0, min_height=0, anaerobic_train_effect=0)
    adapter = _connected_adapter([_sport_record(payload)])
    workout = _collect_workouts(adapter)[0]
    assert workout.avg_height_m == 0.0
    assert workout.min_height_m == 0.0
    assert workout.anaerobic_train_effect == 0.0
