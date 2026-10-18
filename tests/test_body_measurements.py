from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
from mi_fitness_mcp.storage import Database


def _connected_adapter(records):
    adapter = MiFitnessCloudAdapter(user_id="123456", pass_token="token")
    adapter._connected = True
    adapter._client = object()  # is_connected() only checks it is not None

    async def fake_fetch_key(key, start_date, end_date, region=None):
        return records

    adapter._fetch_key = fake_fetch_key
    return adapter


def _collect(adapter):
    async def run():
        return [
            measurement
            async for measurement in adapter.iter_body_measurements(
                "2026-08-01", "2026-08-31"
            )
        ]

    return asyncio.run(run())


def test_iter_body_measurements_skips_missing_or_zero_weight():
    records = [
        {"time": 1754000000, "value": json.dumps({"weight": 72.5, "bmi": 23.0})},
        # weight=0: 会触发 BodyMeasurement 的 gt=0 校验, 必须跳过而不是中断生成器。
        {"time": 1754000100, "value": json.dumps({"weight": 0, "bmi": 20.0})},
        # weight 缺失同样跳过。
        {"time": 1754000200, "value": json.dumps({"bmi": 21.0})},
    ]

    measurements = _collect(_connected_adapter(records))

    assert len(measurements) == 1
    assert measurements[0].weight_kg == 72.5
    assert measurements[0].bmi == 23.0


def test_iter_body_measurements_treats_zero_bmi_as_unmeasured():
    records = [
        {"time": 1754000000, "value": json.dumps({"weight": 72.5, "bmi": 0})},
    ]

    measurements = _collect(_connected_adapter(records))

    assert len(measurements) == 1
    assert measurements[0].weight_kg == 72.5
    assert measurements[0].bmi is None


@pytest.mark.parametrize("rate, expected", [(60, 48.0), ("62.5", 50.0), (100, 80.0)])
def test_muscle_rate_is_converted_to_kilograms(rate, expected):
    records = [{"time": 1754000000, "value": json.dumps({"weight": 80, "muscle_rate": rate})}]
    measurement = _collect(_connected_adapter(records))[0]
    assert measurement.muscle_mass_kg == pytest.approx(expected)


@pytest.mark.parametrize("rate", [None, 0, "0", -1, 101, "bad", "NaN", "Infinity"])
def test_unavailable_or_invalid_muscle_rate_preserves_weight(rate):
    records = [{"time": 1754000000, "value": json.dumps({"weight": 80, "muscle_rate": rate})}]
    measurement = _collect(_connected_adapter(records))[0]
    assert measurement.weight_kg == 80
    assert measurement.muscle_mass_kg is None


@pytest.mark.parametrize("weight", [None, 0, -1, "NaN", "Infinity"])
def test_muscle_rate_without_valid_weight_is_not_converted(weight):
    records = [{"time": 1754000000, "value": json.dumps({"weight": weight, "muscle_rate": 60})}]
    assert _collect(_connected_adapter(records)) == []


def test_resync_replaces_cached_percentage_without_double_conversion(tmp_path):
    records = [{"time": 1754000000, "value": json.dumps({"weight": 80, "muscle_rate": 60})}]
    measurement = _collect(_connected_adapter(records))[0]
    db = Database(tmp_path / "synthetic.db")
    db.insert_body_measurement(measurement.model_copy(update={"muscle_mass_kg": 60}))
    assert db.insert_body_measurement(measurement) is False
    assert db.insert_body_measurement(measurement) is False
    with sqlite3.connect(db.db_path) as conn:
        rows = conn.execute("SELECT muscle_mass_kg FROM body_measurements").fetchall()
    assert rows == [(48.0,)]
