"""Regression: Mi Fitness cloud sleep `state` code table.

Synthetic regression for the community-reported table in #13 (2026-09-17):
2=deep, 3=light, 4=rem, 5=awake. The earlier inherited table mislabeled deep,
REM and awake; these fixtures do not independently verify cloud encoding.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

# Synthetic epoch timestamp; exact value is irrelevant to stage math.
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
    # Unverified/unknown codes retain a light fallback, not a verified meaning.
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
    # 60-minute night: 10 deep + 30 light + 15 rem + 5 awake.
    # payload "duration" is in MINUTES (matches the real cloud payload);
    # segment start_time/end_time are epoch seconds.
    payload = {
        "bedtime": BASE,
        "wake_up_time": BASE + 3600,
        "duration": 60,
        "sleep_deep_duration": 10,
        "sleep_light_duration": 30,
        "sleep_rem_duration": 15,
        "sleep_awake_duration": 5,
        "items": [
            {"start_time": BASE, "end_time": BASE + 600, "state": 2},        # deep 10
            {"start_time": BASE + 600, "end_time": BASE + 2400, "state": 3},  # light 30
            {"start_time": BASE + 2400, "end_time": BASE + 3300, "state": 4}, # rem 15
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

    # Distinct stage durations also catch accidental swaps between deep and REM.
    # Stage sums must equal the synthetic top-level per-stage durations.
    assert totals["deep"] == 10
    assert totals["light"] == 30
    assert totals["rem"] == 15
    assert totals["awake"] == 5

    # header consistency: awake from top-level field, asleep = duration - awake
    assert session.duration_minutes == 60
    assert session.time_awake_minutes == 5
    assert session.time_asleep_minutes == 55
    assert sum(totals.values()) == session.duration_minutes
    assert totals["deep"] + totals["light"] + totals["rem"] == session.time_asleep_minutes
