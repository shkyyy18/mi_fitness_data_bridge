from __future__ import annotations

import asyncio
import json

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter


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
