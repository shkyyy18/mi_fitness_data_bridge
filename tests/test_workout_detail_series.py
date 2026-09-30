"""workout_detail_series：秒级明细曲线的契约与语义测试（合成数据）。

覆盖：全分辨率点、自适应降采样、0 值剔除、time_in_zone、
空明细信封、未知 workout/metric 报错。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mi_fitness_mcp.models import Workout, WorkoutSample
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database


def _seed(db: Database, *, hr_zeros: int = 3) -> str:
    workout_id = "synthetic-detail-run"
    db.insert_workout(
        Workout(
            id=f"mi_fitness_workout_{workout_id}",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id="synthetic-test-user",
            workout_id=workout_id,
            activity_type="running",
            start_at=datetime(2026, 9, 25, 14, 1, 31),
            end_at=datetime(2026, 9, 25, 14, 39, 29),
            duration_minutes=37,
            max_heart_rate_bpm=170,
        )
    )
    samples = []
    for offset in range(100):
        # 心率：前 hr_zeros 秒为 0（传感器未就绪），之后 150 + 10*sin 波形
        hr = 0 if offset < hr_zeros else 150 + (offset % 20)
        sample = WorkoutSample(
            id=f"mi_fitness_sample_{workout_id}_{offset}",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id="synthetic-test-user",
            workout_id=workout_id,
            offset_seconds=offset,
            timestamp=datetime(2026, 9, 25, 14, 1, 31),
            heart_rate_bpm=hr,
            cadence=0 if offset < hr_zeros else 160 + (offset % 15),
            pace_sec_per_km=570 if offset >= hr_zeros else None,
            speed_mps=None,
        )
        samples.append(sample)
    db.insert_workout_detail_samples(samples)
    return workout_id


@pytest.fixture()
def service(tmp_path):
    db = Database(tmp_path / "mi_fitness.db")
    workout_id = _seed(db)
    return QueryService(db, "synthetic-test-user"), workout_id


def test_full_resolution_series(service):
    svc, workout_id = service
    result = svc.get_workout_detail_series(workout_id, metric="heart_rate", max_points=500)

    assert result["contract_version"] == "agent-safe-series/v1"
    assert result["unit"] == "bpm"
    assert result["downsampled"] is False
    assert result["method"] == "none"
    # 100 个点里 3 个 0 值被剔除
    assert result["source_points"] == 97
    assert result["returned_points"] == 97
    assert result["points"][0] == {"t": 3, "value": 153}
    assert result["stats"]["min"] == 150
    assert result["stats"]["max"] == 169
    assert result["data_quality"]["zero_or_null_samples_excluded"] == 3
    assert result["data_quality"]["sample_interval_seconds"] == 1.0


def test_heart_rate_time_in_zone_uses_workout_max(service):
    svc, workout_id = service
    result = svc.get_workout_detail_series(workout_id, metric="heart_rate")
    zones = result["time_in_zone"]
    assert zones["reference_max_bpm"] == 170
    assert zones["reference_source"] == "activity_recorded_max"
    # 样本 150-169，全部 >= 153（0.9*170）：几乎全在 zone 5
    z5 = zones["zones"][4]
    assert z5["seconds"] > 0
    assert zones["zones"][0]["seconds"] == 0


def test_cadence_series_without_time_in_zone(service):
    svc, workout_id = service
    result = svc.get_workout_detail_series(workout_id, metric="cadence")
    assert result["unit"] == "spm"
    assert result["time_in_zone"] is None
    assert result["stats"]["avg"] == pytest.approx(166.5, abs=1.5)


def test_pace_series(service):
    svc, workout_id = service
    result = svc.get_workout_detail_series(workout_id, metric="pace")
    assert result["unit"] == "sec_per_km"
    assert result["stats"]["min"] == 570
    assert result["stats"]["max"] == 570


def test_downsampling_discloses_method_and_buckets(service):
    svc, workout_id = service
    result = svc.get_workout_detail_series(workout_id, metric="heart_rate", max_points=10)

    assert result["downsampled"] is True
    assert result["method"] == "time_bucket_mean"
    assert result["returned_points"] <= 10
    assert result["resolution_seconds"] >= result["requested_resolution_seconds"]
    for point in result["points"]:
        assert "min" in point and "max" in point and "samples" in point
    # stats 仍按全分辨率样本计算
    assert result["stats"]["max"] == 169


def test_max_points_hard_cap(service):
    svc, workout_id = service
    result = svc.get_workout_detail_series(workout_id, metric="heart_rate", max_points=9999)
    assert result["downsampled"] is False  # 97 个点远低于 500 硬顶


def test_unknown_workout_raises(service):
    svc, _ = service
    with pytest.raises(ValueError, match="Unknown workout_id"):
        svc.get_workout_detail_series("no-such-workout")


def test_unknown_metric_raises(service):
    svc, workout_id = service
    with pytest.raises(ValueError, match="Unsupported workout detail metric"):
        svc.get_workout_detail_series(workout_id, metric="power")


def test_workout_without_detail_returns_empty_envelope(tmp_path):
    db = Database(tmp_path / "mi_fitness.db")
    db.insert_workout(
        Workout(
            id="w-none",
            provider="mi_fitness",
            source_type="cloud_session",
            user_id="synthetic-test-user",
            workout_id="wo-none",
            activity_type="running",
            start_at=datetime(2026, 9, 24, 14, 0),
            end_at=datetime(2026, 9, 24, 14, 30),
            duration_minutes=30,
        )
    )
    svc = QueryService(db, "synthetic-test-user")
    result = svc.get_workout_detail_series("wo-none")
    assert result["points"] == []
    assert result["stats"] is None
    assert result["data_quality"]["missing_metrics"] == ["heart_rate"]


@pytest.mark.parametrize("max_points", [1, 2, 100, 500, 1000])
def test_detail_output_cap_includes_offsets_outside_report(service, max_points):
    svc, workout_id = service
    # This nominal activity is shorter than its device-recorded detail span.
    with svc.db._get_connection() as conn:
        conn.execute(
            "UPDATE workouts SET end_at = ? WHERE user_id = ? AND workout_id = ?",
            ("2026-09-25T14:09:51", "synthetic-test-user", workout_id),
        )
        conn.commit()
    records = [
        WorkoutSample(
            id=f"synthetic-outside-{offset}", provider="mi_fitness",
            source_type="cloud_session", user_id="synthetic-test-user",
            workout_id=workout_id, offset_seconds=offset,
            timestamp=datetime(2026, 9, 25, 14, 1, 31), heart_rate_bpm=160,
        )
        for offset in range(-2, 1001)
    ]
    svc.db.insert_workout_detail_samples(records)
    result = svc.get_workout_detail_series(workout_id, resolution=1, max_points=max_points)
    assert result["returned_points"] <= min(max_points, 500)
    assert result["source_points"] == 1003
    assert result["stats"]["avg"] == 160
    assert sum(p["samples"] for p in result["points"]) == 1003
    assert result["points"][0]["t"] == -2
    assert result["downsampled"] is True
