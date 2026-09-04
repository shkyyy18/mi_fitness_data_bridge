"""Regression tests: records with missing or pre-2000 `time` fields must be
skipped and counted instead of collapsing ids to `..._0` and timestamps to 1970.
"""

from __future__ import annotations

import asyncio
import json
import logging

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter


def _connected_adapter() -> MiFitnessCloudAdapter:
    adapter = MiFitnessCloudAdapter(user_id="123456", pass_token="token")
    adapter._connected = True
    adapter._client = object()  # is_connected() only checks it is not None
    return adapter


def test_iter_body_measurements_skips_missing_and_pre_2000_time(caplog):
    adapter = _connected_adapter()
    records = [
        {"time": 1754000000, "value": json.dumps({"weight": 72.5})},
        # time 早于 2000 年：旧代码会照收，timestamp 塌缩到 1970。
        {"time": 946684799, "value": json.dumps({"weight": 70.0})},
        # time 缺失：旧代码 id 会塌缩成 mi_fitness_weight_0。
        {"value": json.dumps({"weight": 71.0})},
        # time 不是数字。
        {"time": "not-a-number", "value": json.dumps({"weight": 69.0})},
    ]

    async def fake_fetch_key(key, start_date, end_date, region=None):
        return records

    adapter._fetch_key = fake_fetch_key

    async def collect():
        return [
            m async for m in adapter.iter_body_measurements("2026-08-01", "2026-08-31")
        ]

    with caplog.at_level(logging.WARNING):
        measurements = asyncio.run(collect())

    assert len(measurements) == 1
    assert measurements[0].id == "mi_fitness_weight_1754000000"
    assert measurements[0].timestamp.year == 2025
    assert "body_measurements: skipped 3 malformed record(s)" in caplog.text


def test_iter_heart_rate_skips_records_without_valid_time(caplog):
    adapter = _connected_adapter()
    by_key = {
        "heart_rate": [
            {"time": 1754000000, "value": json.dumps({"bpm": 72})},
            {"value": json.dumps({"bpm": 75})},
        ],
        "resting_heart_rate": [
            {"time": 1754000100, "value": json.dumps({"bpm": 55})},
            # date_time 与 time 都缺失。
            {"value": json.dumps({"bpm": 60})},
        ],
    }

    async def fake_fetch_key(key, start_date, end_date, region=None):
        return by_key[key]

    adapter._fetch_key = fake_fetch_key

    async def collect():
        return [s async for s in adapter.iter_heart_rate("2026-08-01", "2026-08-31")]

    with caplog.at_level(logging.WARNING):
        samples = asyncio.run(collect())

    assert [s.id for s in samples] == [
        "mi_fitness_hr_1754000000",
        "mi_fitness_resting_hr_1754000100",
    ]
    assert all(not s.id.endswith("_0") for s in samples)
    assert all(s.timestamp.year > 2000 for s in samples)
    assert "heart_rate: skipped 2 malformed record(s)" in caplog.text


def test_iter_spo2_skips_pre_2000_payload_timestamp(caplog):
    adapter = _connected_adapter()
    records = [
        {"time": 1754000000, "value": json.dumps({"spo2": 98})},
        # payload 里的 time 早于 2000 年。
        {"time": 1754000001, "value": json.dumps({"time": 123, "spo2": 97})},
    ]

    async def fake_fetch_key(key, start_date, end_date, region=None):
        return records

    adapter._fetch_key = fake_fetch_key

    async def collect():
        return [s async for s in adapter.iter_spo2("2026-08-01", "2026-08-31")]

    with caplog.at_level(logging.WARNING):
        samples = asyncio.run(collect())

    assert len(samples) == 1
    assert samples[0].spo2_pct == 98
    assert "spo2: skipped 1 malformed record(s)" in caplog.text
