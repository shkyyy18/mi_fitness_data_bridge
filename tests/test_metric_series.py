"""Advertised metric enums and reducers must actually work (synthetic SQLite)."""

from datetime import datetime

import pytest

from mi_fitness_mcp.models import BodyMeasurement, DailyActivity
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.storage import Database

BASE = {
    "provider": "mi_fitness",
    "source_type": "cloud_session",
    "user_id": "synthetic-metric-user",
}


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / "synthetic.db")
    # Insert out of order to catch accidental insertion-order 'latest'.
    for index, (date, steps) in enumerate([("2026-01-07", 300), ("2026-01-05", 100)]):
        db.insert_daily_activity(
            DailyActivity(
                id=f"activity-{index}",
                date=date,
                steps=steps,
                distance_m=steps * 0.5,
                active_kcal=steps * 0.1,
                **BASE,
            )
        )
    for index, (timestamp, weight) in enumerate(
        [
            ("2026-01-07T08:00:00", 72),
            ("2026-01-05T08:00:00", 75),
            ("2026-01-05T18:00:00", 74),
        ]
    ):
        db.insert_body_measurement(
            BodyMeasurement(
                id=f"body-{index}",
                timestamp=datetime.fromisoformat(timestamp),
                weight_kg=weight,
                **BASE,
            )
        )
    return QueryService(db, BASE["user_id"])


def test_weight_reads_body_table_and_latest_measurement_per_day(service):
    assert service.get_metric_series("weight_kg", "2026-01-01", "2026-01-31") == [
        {"date": "2026-01-05", "value": 74},
        {"date": "2026-01-07", "value": 72},
    ]
    assert service.get_metric_series("weight_kg", "2026-01-08", "2026-01-31") == []


@pytest.mark.parametrize("granularity,bucket", [("week", "2026-01-05"), ("month", "2026-01-01")])
@pytest.mark.parametrize(
    "aggregation,expected", [("sum", 146), ("avg", 73), ("min", 72), ("max", 74), ("latest", 72)]
)
def test_weight_reducers_use_daily_values_without_zero_filling(
    service, granularity, bucket, aggregation, expected
):
    assert service.get_metric_series(
        "weight_kg", "2026-01-01", "2026-01-31", granularity, aggregation
    ) == [{"date": bucket, "value": expected}]


@pytest.mark.parametrize(
    "metric,expected", [("steps", 300), ("distance_m", 150), ("active_kcal", 30)]
)
@pytest.mark.parametrize("granularity", ["week", "month"])
def test_activity_latest_returns_last_day_not_sum(service, metric, expected, granularity):
    series = service.get_metric_series(metric, "2026-01-01", "2026-01-31", granularity, "latest")
    assert series[0]["value"] == expected


@pytest.mark.parametrize("aggregation", ["sum", "avg", "min", "max", "latest"])
def test_daily_activity_ignores_reducer_as_documented(service, aggregation):
    assert service.get_metric_series("steps", "2026-01-01", "2026-01-31", "day", aggregation) == [
        {"date": "2026-01-05", "value": 100},
        {"date": "2026-01-07", "value": 300},
    ]


@pytest.mark.parametrize(
    "metric,granularity,aggregation",
    [("unsupported", "day", "sum"), ("steps", "hour", "sum"), ("steps", "day", "median")],
)
def test_invalid_series_options_fail_explicitly(service, metric, granularity, aggregation):
    with pytest.raises(ValueError):
        service.get_metric_series(metric, "2026-01-01", "2026-01-31", granularity, aggregation)
