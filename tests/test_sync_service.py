from __future__ import annotations

import asyncio

import pytest

from mi_fitness_mcp.services.sync_service import SyncService


class ConnectedAdapter:
    def is_connected(self) -> bool:
        return True


class FakeDatabase:
    def __init__(self, state=None):
        self.state = state

    def get_sync_state(self, data_type):
        return self.state


@pytest.mark.parametrize(
    ("lookback_days", "chunk_days", "message"),
    [
        (0, 7, "default_lookback_days must be at least 1"),
        (30, 0, "chunk_days must be at least 1"),
    ],
)
def test_sync_service_rejects_non_positive_ranges(lookback_days, chunk_days, message):
    with pytest.raises(ValueError, match=message):
        SyncService(
            ConnectedAdapter(),
            FakeDatabase(),
            default_lookback_days=lookback_days,
            chunk_days=chunk_days,
        )


def test_sync_service_chunks_requested_range_and_aggregates_counts():
    service = SyncService(ConnectedAdapter(), FakeDatabase(), chunk_days=3)
    calls: list[tuple[str, str, str]] = []

    async def fake_sync_range(data_type, start_date, end_date):
        calls.append((data_type, start_date, end_date))
        return {"added": 1, "updated": 2, "skipped": 3}

    service._sync_range = fake_sync_range
    result = asyncio.run(
        service.sync_data_type(
            "daily_activity",
            start_date="2026-07-01",
            end_date="2026-07-07",
        )
    )

    assert calls == [
        ("daily_activity", "2026-07-01", "2026-07-03"),
        ("daily_activity", "2026-07-04", "2026-07-06"),
        ("daily_activity", "2026-07-07", "2026-07-07"),
    ]
    assert result["status"] == "ok"
    assert result["added"] == 3
    assert result["updated"] == 6
    assert result["skipped"] == 9
    assert service.sync_in_progress is False


def test_sync_service_returns_partial_result_and_releases_lock_after_chunk_failure():
    service = SyncService(ConnectedAdapter(), FakeDatabase(), chunk_days=2)
    calls = 0

    async def fake_sync_range(data_type, start_date, end_date):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic chunk failure")
        return {"added": 2, "updated": 1, "skipped": 0}

    service._sync_range = fake_sync_range
    result = asyncio.run(
        service.sync_data_type(
            "daily_activity",
            start_date="2026-07-01",
            end_date="2026-07-05",
        )
    )

    assert result["status"] == "partial"
    assert result["added"] == 2
    assert result["updated"] == 1
    assert result["error_code"] == "RuntimeError"
    assert result["chunks"][1]["status"] == "error"
    assert service.sync_in_progress is False


class RangeAdapter(ConnectedAdapter):
    """Yields three daily_activity records, the middle one is bad."""

    def iter_daily_activity(self, start_date, end_date):
        async def gen():
            from datetime import datetime
            from types import SimpleNamespace

            yield SimpleNamespace(id="good-1", collected_at=datetime(2026, 7, 1, 8))
            yield SimpleNamespace(id="bad-1", collected_at=datetime(2026, 7, 2, 8))
            yield SimpleNamespace(id="good-2", collected_at=datetime(2026, 7, 3, 8))

        return gen()


class RangeDatabase(FakeDatabase):
    def __init__(self):
        super().__init__()
        self.sync_state_updates = []

    def insert_daily_activity(self, record):
        if record.id == "bad-1":
            raise ValueError("synthetic bad record")
        return True

    def update_sync_state(self, data_type, last_ts):
        self.sync_state_updates.append((data_type, last_ts))


def test_sync_range_isolates_bad_records_and_advances_watermark():
    from datetime import datetime

    db = RangeDatabase()
    service = SyncService(RangeAdapter(), db, chunk_days=7)

    result = asyncio.run(service._sync_range("daily_activity", "2026-07-01", "2026-07-07"))

    # 坏记录不中断本 range：两条好记录照常入库，skipped 真实自增。
    assert result["added"] == 2
    assert result["skipped"] == 1
    assert len(result["bad_records"]) == 1
    bad = result["bad_records"][0]
    assert bad["data_type"] == "daily_activity"
    assert bad["record_id"] == "bad-1"
    assert bad["error_type"] == "ValueError"
    assert "synthetic bad record" in bad["error"]
    # 水位只用成功记录的 last_ts，坏记录不能卡住水位。
    assert db.sync_state_updates == [("daily_activity", datetime(2026, 7, 3, 8))]


def test_sync_range_caps_bad_records_at_twenty():
    from datetime import datetime
    from types import SimpleNamespace

    class AllBadAdapter(ConnectedAdapter):
        def iter_spo2(self, start_date, end_date):
            async def gen():
                for i in range(25):
                    yield SimpleNamespace(id=f"bad-{i}", timestamp=datetime(2026, 7, 1))

            return gen()

    class AllBadDatabase(FakeDatabase):
        def insert_spo2_sample(self, record):
            raise RuntimeError("always fails")

    service = SyncService(AllBadAdapter(), AllBadDatabase(), chunk_days=7)
    result = asyncio.run(service._sync_range("spo2", "2026-07-01", "2026-07-07"))

    assert result["skipped"] == 25
    assert len(result["bad_records"]) == 20


def test_sync_data_type_surfaces_bad_records_in_chunks():
    db = RangeDatabase()
    service = SyncService(RangeAdapter(), db, chunk_days=7)

    result = asyncio.run(
        service.sync_data_type(
            "daily_activity", start_date="2026-07-01", end_date="2026-07-03"
        )
    )

    assert result["status"] == "ok"
    assert result["added"] == 2
    assert result["skipped"] == 1
    assert result["chunks"][0]["bad_records"][0]["record_id"] == "bad-1"
