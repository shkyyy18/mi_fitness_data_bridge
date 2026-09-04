"""issue #11 回归测试：手机+手环同分钟并行上报的步数去重。"""
import asyncio
import json
import unittest

from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter


def _item(epoch_seconds: int, steps: int, distance: float = 0.0, calories: float = 0.0) -> dict:
    return {
        "time": epoch_seconds,
        "zone_offset": 28800,  # Asia/Shanghai
        "zone_name": "Asia/Shanghai",
        "value": json.dumps({"steps": steps, "distance": distance, "calories": calories}),
    }


class TestDailyActivityDedup(unittest.TestCase):
    def _run(self, records: list[dict]) -> list:
        adapter = MiFitnessCloudAdapter(user_id="u", pass_token="t", region="cn")

        async def fake_fetch(key, start, end, region=None):
            return records if key == "steps" else []

        adapter._fetch_key = fake_fetch
        adapter._connected = True
        adapter._client = object()  # is_connected() 仅需非空，本测试不走网络

        async def collect():
            return [a async for a in adapter.iter_daily_activity("2026-09-03", "2026-09-03")]

        return asyncio.run(collect())

    def test_parallel_sources_same_minute_take_max_not_sum(self):
        # 2026-09-03 09:24 上海：手机 44 步 + 手环 17 步同一分钟，应取 44 而非 61
        t = 1756897440  # 2026-09-03T09:24:00+08:00
        records = [_item(t, 44, 30.0, 2.0), _item(t, 17, 12.0, 1.0)]
        days = self._run(records)
        self.assertEqual(1, len(days))
        self.assertEqual(44, days[0].steps)
        self.assertEqual(30.0, days[0].distance_m)

    def test_distinct_minutes_still_sum(self):
        t1 = 1756897440  # 09:24
        t2 = t1 + 60  # 09:25
        days = self._run([_item(t1, 44), _item(t2, 17)])
        self.assertEqual(61, days[0].steps)

    def test_single_source_day_unchanged(self):
        t1 = 1756897440
        days = self._run([_item(t1, 100), _item(t1 + 120, 50)])
        self.assertEqual(150, days[0].steps)


if __name__ == "__main__":
    unittest.main()
