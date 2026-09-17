"""Regression: Mi Fitness cloud sleep `state` code table.

Verified against the authoritative top-level sleep_deep/light/rem/awake_duration
fields on 2026-09-17: 2=deep, 3=light, 4=rem, 5=awake. The earlier inherited
table (1=deep/2=light/3=light/4=awake/5=rem) mislabeled every stage.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

# base wall-clock ~2026-09-16 02:00 +08:00; exact value irrelevant to stage math
BASE = 1789500000


def _adapter() -> MiFitnessCloudAdapter:
    adapter = MiFitnessCloudAdapter(user_id="1", pass_token="tok")
    adapter._connected = True
    adapter._client = object()
    return adapter


def test_sleep_stage_name_maps_verified_codes():
    adapter = _adapter()
    assert adapter._sleep_stage_name(2) == "deep"
    assert adapter._sleep_stage_name(3) == "light"
    assert adapter._sleep_stage_name(4) == "rem"
    assert adapter._sleep_stage_name(5) == "awake"
    # out-of-bed / unknown codes fall back to light, never to a wrong stage
    assert adapter._sleep_stage_name(1) == "light"
    assert adapter._sleep_stage_name(99) == "light"
    assert adapter._sleep_stage_name(None) == "light"
    assert adapter._sleep_stage_name("bogus") == "light"


def test_old_code_no_longer_mislabels_deep_or_rem():
    # Under the buggy table, deep (real code 2) -> light and rem (real code 4) -> awake.
    adapter = _adapter()
    assert adapter._sleep_stage_name(2) != "light"
    assert adapter._sleep_stage_name(4) != "awake"


def _sleep_item() -> dict:
    # 60-minute night: 10 deep + 35 light + 10 rem + 5 awake.
    # payload "duration" is in MINUTES (matches the real cloud payload);
    # segment start_time/end_time are epoch seconds.
    payload = {
        "bedtime": BASE,
        "wake_up_time": BASE + 3600,
        "duration": 60,
        "sleep_deep_duration": 10,
        "sleep_light_duration": 35,
        "sleep_rem_duration": 10,
        "sleep_awake_duration": 5,
        "items": [
            {"start_time": BASE, "end_time": BASE + 600, "state": 2},        # deep 10
            {"start_time": BASE + 600, "end_time": BASE + 2700, "state": 3},  # light 35
            {"start_time": BASE + 2700, "end_time": BASE + 3300, "state": 4}, # rem 10
            {"start_time": BASE + 3300, "end_time": BASE + 3600, "state": 5}, # awake 5
        ],
    }
    return {"time": BASE + 3600, "sid": "968440370", "zone_offset": 28800, "value": json.dumps(payload)}


def test_iter_sleep_sessions_stages_match_authoritative_durations():
    adapter = _adapter()

    async def _fetch_stub(key: str, s: str, e: str):
        return [_sleep_item()]

    adapter._fetch_key = _fetch_stub

    async def collect():
        return [s async for s in adapter.iter_sleep_sessions("2026-09-15", "2026-09-17")]

    (session,) = asyncio.run(collect())

    totals: Counter[str] = Counter()
    for stage in session.stages:
        totals[stage.stage] += stage.minutes

    # stage sums must equal the top-level authoritative per-stage durations
    assert totals["deep"] == 10
    assert totals["light"] == 35
    assert totals["rem"] == 10
    assert totals["awake"] == 5

    # header consistency: awake from top-level field, asleep = duration - awake
    assert session.duration_minutes == 60
    assert session.time_awake_minutes == 5
    assert session.time_asleep_minutes == 55
