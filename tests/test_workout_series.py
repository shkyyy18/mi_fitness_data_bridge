"""Regression tests for the agent-safe workout_series pipeline (issue #5).

Uses only the synthetic 3-hour ride fixture from tests/synthetic_fixtures.py
(issue #6): 10,800 1 Hz heart rate points with known ground-truth statistics.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from datetime import datetime, timedelta

import pytest

from mi_fitness_mcp import server
from mi_fitness_mcp.models import HeartRateSample, Workout
from mi_fitness_mcp.services.query_service import (
    HARD_MAX_POINTS,
    ZONE_FRACTIONS,
    QueryService,
)
from mi_fitness_mcp.storage import Database
from tests.synthetic_fixtures import (
    SYNTHETIC_RIDE_WORKOUT_ID,
    SYNTHETIC_USER_ID,
    seed_synthetic_ride,
)


@pytest.fixture
def seeded_db(tmp_path):
    db = Database(tmp_path / "synthetic.db")
    bpms = seed_synthetic_ride(db)
    return db, bpms


@pytest.fixture
def service(seeded_db):
    db, _ = seeded_db
    return QueryService(db, SYNTHETIC_USER_ID)


def ground_truth_zone_seconds(bpms: list[int]) -> list[int]:
    reference_max = max(bpms)
    bounds = [int(reference_max * f) for f in ZONE_FRACTIONS]
    zones = [0] * (len(bounds) + 1)
    for bpm in bpms:
        zones[sum(bpm >= bound for bound in bounds)] += 1  # 1 Hz: 1 sample == 1 s
    return zones


def test_downsampled_series_metadata_and_stats(service, seeded_db):
    _, bpms = seeded_db
    result = service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID)

    assert result["downsampled"] is True
    assert result["method"] == "time_bucket_mean"
    assert result["source_points"] == 10_800
    assert 0 < result["returned_points"] <= 400
    assert result["returned_points"] == len(result["points"])

    # Summary stats are computed on the full-resolution series (ground truth).
    stats = result["stats"]
    assert abs(stats["avg"] - statistics.fmean(bpms)) <= 1.0
    assert stats["min"] == min(bpms)
    assert stats["max"] == max(bpms)
    assert stats["p25"] <= stats["p50"] <= stats["p75"]
    assert stats["percentile_method"] == "linear_interpolation"

    # Bucket means stay faithful to the raw average.
    bucket_avg = statistics.fmean(p["value"] for p in result["points"])
    assert abs(bucket_avg - statistics.fmean(bpms)) <= 1.0

    # Time-in-zone matches the ground-truth zone distribution (1 Hz samples).
    truth = ground_truth_zone_seconds(bpms)
    zones = result["time_in_zone"]["zones"]
    assert [z["seconds"] for z in zones] == truth
    assert sum(z["seconds"] for z in zones) == len(bpms)


def test_agent_safe_series_v1_envelope(service):
    result = service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID)

    assert result["contract_version"] == "agent-safe-series/v1"
    assert result["start_time"] == "2026-07-15T08:00:00"
    assert result["t_unit"] == "seconds_from_start"
    assert result["unit"] == "bpm"
    assert result["requested_resolution_seconds"] == 60
    assert result["resolution_seconds"] >= result["requested_resolution_seconds"]

    # points[].t are numeric offsets from start_time, sorted and in range.
    offsets = [p["t"] for p in result["points"]]
    assert all(isinstance(t, int) for t in offsets)
    assert offsets == sorted(offsets)
    assert 0 <= offsets[0] <= offsets[-1] < result["duration_seconds"]

    quality = result["data_quality"]
    assert quality["actual_samples"] == 10_800
    assert quality["expected_samples"] == 10_800
    assert quality["sample_interval_seconds"] == 1.0
    assert quality["coverage_ratio"] == 1.0
    assert quality["coverage_anchor"] == "nominal_duration"

    tiz = result["time_in_zone"]
    assert tiz["reference_source"] == "activity_recorded_max"


def test_max_points_is_hard_capped(service):
    result = service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID, max_points=10_000)
    assert result["downsampled"] is True
    assert result["returned_points"] <= HARD_MAX_POINTS


def test_requested_resolution_honored_when_within_budget(service):
    result = service.get_workout_series(
        SYNTHETIC_RIDE_WORKOUT_ID, resolution=60, max_points=500
    )
    # 3h / 60s = 180 buckets, within budget: keep the requested resolution.
    assert result["resolution_seconds"] == 60
    assert result["returned_points"] == 180


def test_adaptive_resolution_when_budget_too_small(service):
    result = service.get_workout_series(
        SYNTHETIC_RIDE_WORKOUT_ID, resolution=10, max_points=300
    )
    assert result["resolution_seconds"] >= 36  # ceil(10800 / 300)
    assert result["returned_points"] <= 300


def test_short_workout_is_returned_at_full_resolution(tmp_path):
    db = Database(tmp_path / "synthetic.db")
    bpms = seed_synthetic_ride(db, workout_id="synthetic-ride-short", duration_seconds=300)
    service = QueryService(db, SYNTHETIC_USER_ID)

    result = service.get_workout_series("synthetic-ride-short")
    assert result["downsampled"] is False
    assert result["method"] == "none"
    assert result["source_points"] == 300
    assert result["returned_points"] == 300
    assert [p["value"] for p in result["points"]] == bpms
    assert [p["t"] for p in result["points"]] == list(range(300))


def test_unknown_workout_raises(service):
    with pytest.raises(ValueError, match="Unknown workout_id"):
        service.get_workout_series("no-such-workout")


def test_workout_series_includes_all_sample_types_in_window(tmp_path):
    """The cloud adapter only writes passive/active/resting samples; filtering
    by a "workout" sample_type always came back empty. The series must use
    every sample inside the activity window and report the observed types."""
    db = Database(tmp_path / "mixed.db")
    base = {"provider": "mi_fitness", "source_type": "cloud_session", "user_id": SYNTHETIC_USER_ID}
    start = datetime(2026, 7, 15, 8, 0, 0)
    db.insert_workout(
        Workout(
            id="w-mixed",
            workout_id="w-mixed",
            activity_type="running",
            start_at=start,
            end_at=start + timedelta(seconds=2),
            duration_minutes=1,
            **base,
        )
    )
    db.insert_heart_rate_samples(
        [
            HeartRateSample(
                id=f"mixed-{sample_type}",
                timestamp=start + timedelta(seconds=offset),
                bpm=120 + offset,
                sample_type=sample_type,
                **base,
            )
            for offset, sample_type in enumerate(["active", "passive", "resting"])
        ]
    )
    service = QueryService(db, SYNTHETIC_USER_ID)

    result = service.get_workout_series("w-mixed")

    assert result["source_points"] == 3
    assert [p["value"] for p in result["points"]] == [120, 121, 122]
    assert result["data_quality"]["sample_type"] == "active+passive+resting"


def test_workout_series_empty_window_reports_none_sample_type(tmp_path):
    db = Database(tmp_path / "empty.db")
    base = {"provider": "mi_fitness", "source_type": "cloud_session", "user_id": SYNTHETIC_USER_ID}
    start = datetime(2026, 7, 15, 8, 0, 0)
    db.insert_workout(
        Workout(
            id="w-empty",
            workout_id="w-empty",
            activity_type="running",
            start_at=start,
            end_at=start + timedelta(minutes=30),
            duration_minutes=30,
            **base,
        )
    )
    service = QueryService(db, SYNTHETIC_USER_ID)

    result = service.get_workout_series("w-empty")

    assert result["source_points"] == 0
    assert result["data_quality"]["sample_type"] is None


def test_unsupported_metric_raises(service):
    with pytest.raises(ValueError, match="Unsupported workout metric"):
        service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID, metric="power")


def test_invalid_reference_max_hr_raises(service):
    with pytest.raises(ValueError, match="reference_max_hr"):
        service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID, reference_max_hr=0)


def test_head_missing_data_lowers_coverage(tmp_path):
    """Samples missing at the start must show as coverage < 1.0, not a shorter workout."""
    db = Database(tmp_path / "synthetic.db")
    seed_synthetic_ride(db, head_gap_seconds=1200)  # first 20 min missing
    service = QueryService(db, SYNTHETIC_USER_ID)

    result = service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID)
    quality = result["data_quality"]
    assert quality["coverage_anchor"] == "nominal_duration"
    assert quality["expected_samples"] == 10_800
    assert quality["actual_samples"] == 9_600
    assert quality["coverage_ratio"] == pytest.approx(0.889, abs=0.001)
    assert quality["coverage_ratio"] < 1.0
    # First returned point starts ~20 min into the activity.
    assert result["points"][0]["t"] >= 1200


def test_reference_source_observed_max_when_not_recorded(tmp_path):
    db = Database(tmp_path / "synthetic.db")
    bpms = seed_synthetic_ride(
        db, workout_id="synthetic-ride-no-max", recorded_max_hr=False
    )
    service = QueryService(db, SYNTHETIC_USER_ID)

    tiz = service.get_workout_series("synthetic-ride-no-max")["time_in_zone"]
    assert tiz["reference_source"] == "observed_max"
    assert tiz["reference_max_bpm"] == max(bpms)


def test_reference_source_caller_provided(service, seeded_db):
    _, bpms = seeded_db
    result = service.get_workout_series(SYNTHETIC_RIDE_WORKOUT_ID, reference_max_hr=190)
    tiz = result["time_in_zone"]
    assert tiz["reference_source"] == "caller_provided"
    assert tiz["reference_max_bpm"] == 190
    # Caller-provided reference changes zone bounds but not total seconds.
    assert sum(z["seconds"] for z in tiz["zones"]) == len(bpms)


def test_server_tool_roundtrip(service, monkeypatch):
    monkeypatch.setattr(server, "query_service", service)
    tools = asyncio.run(server.list_tools())
    assert "query_workout_series" in {tool.name for tool in tools}
    assert "workout_series" not in {tool.name for tool in tools}

    content = asyncio.run(
        server.call_tool(
            "workout_series", {"workout_id": SYNTHETIC_RIDE_WORKOUT_ID, "max_points": 400}
        )
    )
    payload = json.loads(content[0].text)
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["downsampled"] is True
    assert data["source_points"] == 10_800
    assert data["returned_points"] <= 400
    assert data["method"] == "time_bucket_mean"
    assert data["contract_version"] == "agent-safe-series/v1"
    assert data["t_unit"] == "seconds_from_start"
    assert isinstance(data["points"][0]["t"], int)

    content = asyncio.run(
        server.call_tool(
            "workout_series",
            {"workout_id": SYNTHETIC_RIDE_WORKOUT_ID, "reference_max_hr": 195},
        )
    )
    data = json.loads(content[0].text)["data"]
    assert data["time_in_zone"]["reference_source"] == "caller_provided"
    assert data["time_in_zone"]["reference_max_bpm"] == 195

    error = asyncio.run(server.call_tool("workout_series", {"workout_id": "missing"}))
    assert json.loads(error[0].text)["status"] == "error"


def test_query_workouts_reports_data_quality(service, monkeypatch):
    monkeypatch.setattr(server, "query_service", service)
    content = asyncio.run(
        server.call_tool("query_workouts", {"start_date": "2026-07-15", "end_date": "2026-07-15"})
    )
    payload = json.loads(content[0].text)
    assert payload["status"] == "ok"
    assert payload["data"]["count"] == 1
    quality = payload["data"]["data_quality"]
    assert quality["data_type"] == "workouts"
    assert quality["days_with_data"] == 1
    assert quality["missing_metrics"] == []
