"""Synthetic coverage for query_sleep's main-sleep summary contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from mi_fitness_mcp import server
from mi_fitness_mcp.models import SleepSession
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database

USER_ID = "synthetic-sleep-user"
TZ = timezone(timedelta(hours=8))
BASE = {
    "provider": "mi_fitness",
    "source_type": "cloud_session",
    "user_id": USER_ID,
}


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "sleep-summary.db")


@pytest.fixture
def service(db):
    return QueryService(db, USER_ID)


def _insert_sleep(
    db: Database,
    sleep_id: str,
    start_at: datetime,
    duration: int,
    *,
    asleep: int | None = None,
    awake: int = 0,
    score: int | None = None,
    is_nap: bool = False,
    source_record_id: str | None = "synthetic-source",
) -> None:
    db.insert_sleep_session(
        SleepSession(
            id=f"row-{sleep_id}",
            source_record_id=source_record_id,
            sleep_id=sleep_id,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=duration),
            duration_minutes=duration,
            time_asleep_minutes=duration if asleep is None else asleep,
            time_awake_minutes=awake,
            sleep_score=score,
            is_nap=is_nap,
            **BASE,
        )
    )


def test_summary_selects_longest_main_sleep_and_preserves_raw_sessions(db, service):
    day_one = datetime(2026, 8, 24, 0, 30, tzinfo=TZ)
    day_two = datetime(2026, 8, 25, 23, 15, tzinfo=TZ)
    _insert_sleep(db, "parallel-short", day_one, 420, asleep=400, awake=20, score=78)
    _insert_sleep(db, "parallel-long", day_one, 450, asleep=430, awake=20, score=82)
    _insert_sleep(db, "main-day-two", day_two, 480, asleep=460, awake=20, score=None)
    _insert_sleep(db, "nap", day_two.replace(hour=14), 30, is_nap=True)

    sessions = service.get_sleep_sessions("2026-08-24", "2026-08-27")
    summary = service.get_sleep_summary("2026-08-24", "2026-08-27")

    assert len(sessions) == 4
    assert [row["sleep_id"] for row in summary["main_sessions"]] == [
        "parallel-long",
        "main-day-two",
    ]
    assert summary["metrics"] == {
        "duration_minutes": {"mean": 465.0, "days_with_value": 2},
        "time_asleep_minutes": {"mean": 445.0, "days_with_value": 2},
        "sleep_score": {"mean": 82.0, "days_with_value": 1},
    }
    assert summary["data_quality"] == {
        "status": "partial",
        "date_basis": "local_end_date",
        "raw_session_date_basis": "local_start_date",
        "selection_method": "longest_valid_non_nap_per_wake_date_v1",
        "requested_days": 4,
        "main_sleep_days": 2,
        "coverage_ratio": 0.5,
        "missing_main_sleep_dates": ["2026-08-25", "2026-08-27"],
        "raw_main_sessions": 3,
        "valid_main_sessions": 3,
        "selected_main_sessions": 2,
        "suppressed_parallel_main_sessions": 1,
        "nap_sessions": 1,
        "raw_nap_sessions": 1,
        "invalid_sessions_excluded": 0,
        "invalid_sleep_scores_excluded": 0,
        "sleep_score_days": 1,
        "sleep_score_coverage_ratio": 0.5,
        "provenance_missing_count": 0,
        "mean_basis": "selected_main_sessions_only",
        "sleep_score_basis": "upstream_values_only_no_local_estimation",
        "missing_days_treated_as_zero": False,
    }


def test_summary_rejects_invalid_sessions_and_uses_stable_tie_breaker(db, service):
    start_at = datetime(2026, 8, 24, 1, 0, tzinfo=TZ)
    _insert_sleep(db, "tie-z", start_at, 450)
    _insert_sleep(db, "tie-a", start_at, 450)
    _insert_sleep(db, "zero-duration", start_at + timedelta(days=1), 0)
    _insert_sleep(
        db,
        "asleep-over-duration",
        start_at + timedelta(days=2),
        300,
        asleep=301,
    )

    summary = service.get_sleep_summary("2026-08-24", "2026-08-26")

    assert [row["sleep_id"] for row in summary["main_sessions"]] == ["tie-z"]
    assert summary["data_quality"]["invalid_sessions_excluded"] == 2
    assert summary["data_quality"]["suppressed_parallel_main_sessions"] == 1
    assert summary["data_quality"]["missing_main_sleep_dates"] == [
        "2026-08-25",
        "2026-08-26",
    ]


def test_summary_includes_previous_date_session_by_local_wake_date(db, service):
    start_at = datetime(2026, 8, 25, 23, 30, tzinfo=TZ)
    _insert_sleep(db, "cross-midnight", start_at, 465, asleep=450, awake=15, score=87)

    summary = service.get_sleep_summary("2026-08-26", "2026-08-26")

    assert [row["sleep_id"] for row in summary["main_sessions"]] == ["cross-midnight"]
    assert summary["data_quality"]["main_sleep_days"] == 1
    assert summary["data_quality"]["missing_main_sleep_dates"] == []


def test_sleep_handler_adds_summary_without_changing_session_count(db, service, monkeypatch):
    start_at = datetime(2026, 8, 24, 1, 0, tzinfo=TZ)
    _insert_sleep(db, "main", start_at, 450, score=85)
    _insert_sleep(db, "nap", start_at.replace(hour=14), 30, is_nap=True)
    monkeypatch.setattr(server, "query_service", service)

    result = asyncio.run(
        server._handle_query_sleep(
            {
                "start_date": "2026-08-24",
                "end_date": "2026-08-24",
                "include_naps": False,
            }
        )
    )

    assert result["data"]["count"] == 1
    assert [row["sleep_id"] for row in result["data"]["sessions"]] == ["main"]
    assert result["data"]["main_sessions"][0]["sleep_id"] == "main"
    assert result["data"]["data_quality"]["nap_sessions"] == 1
    assert result["data"]["data_quality"]["status"] == "complete"


def test_handler_keeps_start_date_sessions_separate_from_wake_date_summary(
    db, service, monkeypatch
):
    start_at = datetime(2026, 8, 25, 23, 30, tzinfo=TZ)
    _insert_sleep(db, "cross-midnight", start_at, 465, asleep=450, awake=15, score=87)
    monkeypatch.setattr(server, "query_service", service)

    result = asyncio.run(
        server._handle_query_sleep(
            {"start_date": "2026-08-26", "end_date": "2026-08-26"}
        )
    )

    assert result["data"]["sessions"] == []
    assert result["data"]["count"] == 0
    assert [row["sleep_id"] for row in result["data"]["main_sessions"]] == [
        "cross-midnight"
    ]


def test_complete_coverage_does_not_require_score_or_provenance(db, service):
    start_at = datetime(2026, 8, 24, 0, 30, tzinfo=TZ)
    _insert_sleep(db, "main", start_at, 450, score=None, source_record_id=None)

    summary = service.get_sleep_summary("2026-08-24", "2026-08-24")

    assert summary["data_quality"]["status"] == "complete"
    assert summary["data_quality"]["sleep_score_coverage_ratio"] == 0.0
    assert summary["data_quality"]["provenance_missing_count"] == 1


def test_invalid_sleep_score_is_excluded_without_failing_query(db, service):
    start_at = datetime(2026, 8, 24, 0, 30, tzinfo=TZ)
    _insert_sleep(db, "main", start_at, 450, score=85)
    with db._get_connection() as connection:
        connection.execute(
            "UPDATE sleep_sessions SET sleep_score = ? WHERE sleep_id = ?",
            ("not-a-score", "main"),
        )
        connection.commit()

    summary = service.get_sleep_summary("2026-08-24", "2026-08-24")

    assert summary["metrics"]["sleep_score"] == {"mean": None, "days_with_value": 0}
    assert summary["data_quality"]["invalid_sleep_scores_excluded"] == 1


def test_summary_excludes_sleep_that_wakes_after_window(db, service):
    start_at = datetime(2026, 8, 24, 23, 30, tzinfo=TZ)
    _insert_sleep(db, "next-day-wake", start_at, 465, score=87)

    summary = service.get_sleep_summary("2026-08-24", "2026-08-24")

    assert summary["main_sessions"] == []
    assert summary["data_quality"]["missing_main_sleep_dates"] == ["2026-08-24"]


def test_raw_session_payload_keeps_existing_is_nap_type(db, service):
    start_at = datetime(2026, 8, 24, 14, 0, tzinfo=TZ)
    _insert_sleep(db, "nap", start_at, 30, is_nap=True)

    sessions = service.get_sleep_sessions("2026-08-24", "2026-08-24")

    assert sessions[0]["is_nap"] == 1
    assert isinstance(sessions[0]["is_nap"], int)


def test_summary_rejects_reversed_date_window(service):
    with pytest.raises(ValueError, match="start_date must not be after end_date"):
        service.get_sleep_summary("2026-08-25", "2026-08-24")
