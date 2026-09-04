"""Regression tests: ON CONFLICT DO UPDATE must refresh every mutable column.

Earlier versions silently kept stale values for bone_mass / visceral_fat /
basal_metabolism / metabolic_age (body_measurements), end_at / activity_type /
pace / total_steps (workouts) and start_at / end_at / is_nap (sleep_sessions).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from mi_fitness_mcp.models import BodyMeasurement, SleepSession, Workout
from mi_fitness_mcp.storage import Database


def _db(tmp_path):
    return Database(tmp_path / "mi_fitness.db")


def _body_measurement(**overrides) -> BodyMeasurement:
    values = {
        "id": "m-1",
        "provider": "mi_fitness",
        "source_type": "cloud_session",
        "user_id": "u-1",
        "timestamp": datetime(2026, 7, 1, 8),
        "weight_kg": 70.0,
    }
    values.update(overrides)
    return BodyMeasurement(**values)


def test_body_measurement_upsert_updates_body_composition_columns(tmp_path):
    db = _db(tmp_path)
    db.insert_body_measurement(_body_measurement())
    updated = db.insert_body_measurement(
        _body_measurement(
            weight_kg=71.5,
            bone_mass_kg=3.1,
            visceral_fat_score=9,
            basal_metabolism_kcal=1500,
            metabolic_age=32,
        )
    )

    assert updated is False
    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute(
            "SELECT weight_kg, bone_mass_kg, visceral_fat_score,"
            " basal_metabolism_kcal, metabolic_age FROM body_measurements WHERE id = 'm-1'"
        ).fetchone()
    assert tuple(row) == (71.5, 3.1, 9, 1500, 32)


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


def test_workout_upsert_updates_end_time_type_pace_and_steps(tmp_path):
    db = _db(tmp_path)
    db.insert_workout(_workout())
    updated = db.insert_workout(
        _workout(
            activity_type="trail_run",
            end_at=datetime(2026, 7, 1, 7, 30),
            duration_minutes=90,
            avg_pace_sec_per_km=360.5,
            max_pace_sec_per_km=300.0,
            total_steps=12000,
        )
    )

    assert updated is False
    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute(
            "SELECT activity_type, end_at, duration_minutes, avg_pace_sec_per_km,"
            " max_pace_sec_per_km, total_steps FROM workouts WHERE id = 'w-1'"
        ).fetchone()
    assert row[0] == "trail_run"
    assert row[1] == "2026-07-01T07:30:00"
    assert tuple(row[2:]) == (90, 360.5, 300.0, 12000)


def _sleep(**overrides) -> SleepSession:
    values = {
        "id": "s-1",
        "provider": "mi_fitness",
        "source_type": "cloud_session",
        "user_id": "u-1",
        "sleep_id": "sl-1",
        "start_at": datetime(2026, 6, 30, 23),
        "end_at": datetime(2026, 7, 1, 7),
        "duration_minutes": 480,
        "time_asleep_minutes": 450,
        "time_awake_minutes": 30,
    }
    values.update(overrides)
    return SleepSession(**values)


def test_sleep_upsert_updates_start_end_and_nap_flag(tmp_path):
    db = _db(tmp_path)
    db.insert_sleep_session(_sleep())
    updated = db.insert_sleep_session(
        _sleep(
            start_at=datetime(2026, 6, 30, 23, 15),
            end_at=datetime(2026, 7, 1, 7, 5),
            is_nap=True,
        )
    )

    assert updated is False
    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute(
            "SELECT start_at, end_at, is_nap FROM sleep_sessions WHERE id = 's-1'"
        ).fetchone()
    assert tuple(row) == ("2026-06-30T23:15:00", "2026-07-01T07:05:00", 1)
