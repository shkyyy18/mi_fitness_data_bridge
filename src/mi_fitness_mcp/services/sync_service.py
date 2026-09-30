"""Sync service for importing data from adapters to database."""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from mi_fitness_mcp.adapters.base import DataAdapter
from mi_fitness_mcp.storage import Database

logger = logging.getLogger(__name__)


class SyncService:
    """Service for synchronizing data from adapters to local database."""

    def __init__(
        self,
        adapter: DataAdapter,
        db: Database,
        default_lookback_days: int = 30,
        chunk_days: int = 7,
    ):
        """Initialize sync service.

        Args:
            adapter: Data source adapter
            db: Database instance
        """
        if default_lookback_days < 1:
            raise ValueError("default_lookback_days must be at least 1")
        if chunk_days < 1:
            raise ValueError("chunk_days must be at least 1")

        self.adapter = adapter
        self.db = db
        self.default_lookback_days = default_lookback_days
        self.chunk_days = chunk_days
        self._sync_lock = asyncio.Lock()
        self._sync_active = False

    @property
    def sync_in_progress(self) -> bool:
        return self._sync_active or self._sync_lock.locked()

    async def _iterate_records(self, records: Any) -> AsyncIterator[Any]:
        if hasattr(records, "__aiter__"):
            async for record in records:
                yield record
            return

        for record in records:
            yield record

    async def sync_data_type(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronize one type while preventing overlapping sync operations."""
        # Check and reserve without awaiting, making this atomic for tasks on this loop.
        if self._sync_active or self._sync_lock.locked():
            raise RuntimeError("Another synchronization is already in progress")
        self._sync_active = True
        try:
            async with self._sync_lock:
                return await self._sync_data_type_unlocked(
                    data_type, start_date, end_date, force_full
                )
        finally:
            self._sync_active = False

    async def _sync_data_type_unlocked(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronize a specific data type.

        Args:
            data_type: Type of data to sync (daily_activity, sleep, workouts, body_measurements)
            start_date: Start date (YYYY-MM-DD), defaults to 30 days ago
            end_date: End date (YYYY-MM-DD), defaults to today
            force_full: Force full sync ignoring last sync state

        Returns:
            Dict with sync statistics
        """
        if not self.adapter.is_connected():
            raise RuntimeError("Adapter not connected")

        if data_type == "workout_detail":
            # 明细不走日期水位/分块：默认扫描全部 workouts 缓存，只拉缺
            # 明细的运动（已有明细的零请求跳过）；显式日期则按范围过滤。
            # 若走水位恢复，首次明细同步之后的日期范围会把更早的运动
            # 永久排除在默认同步之外，无法自动回填。
            return await self._sync_workout_detail_range(start_date, end_date, force_full)

        # 获取上次同步状态，用于增量同步
        last_record_ts = None
        if not force_full:
            state = self.db.get_sync_state(data_type)
            if state and state.get("last_record_timestamp"):
                last_record_ts = datetime.fromisoformat(state["last_record_timestamp"])

        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        except ValueError as exc:
            raise ValueError("Dates must use YYYY-MM-DD format") from exc
        if start_dt is None:
            start_dt = (
                last_record_ts.replace(tzinfo=None)
                if last_record_ts
                else end_dt - timedelta(days=self.default_lookback_days - 1)
            )
            # 水印是时间戳：当日已有数据时它会落在今天日内，晚于按午夜
            # 计算的 end_dt。钳制到 end_dt，否则当天重跑默认同步必报
            # "start_date must not be after end_date"。
            start_dt = min(start_dt, end_dt)
            start_date = start_dt.strftime("%Y-%m-%d")
        if start_dt > end_dt:
            raise ValueError("start_date must not be after end_date")

        chunk_days = getattr(self, "chunk_days", 7)
        totals = {"added": 0, "updated": 0, "skipped": 0}
        chunks = []
        cursor = start_dt
        while cursor <= end_dt:
            chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_dt)
            chunk_start_text = cursor.strftime("%Y-%m-%d")
            chunk_end_text = chunk_end.strftime("%Y-%m-%d")
            try:
                result = await self._sync_range(data_type, chunk_start_text, chunk_end_text)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                chunks.append(
                    {
                        "start_date": chunk_start_text,
                        "end_date": chunk_end_text,
                        "status": "error",
                        "error_code": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                return {
                    "status": "partial"
                    if any(c.get("status") == "ok" for c in chunks)
                    else "error",
                    "data_type": data_type,
                    **totals,
                    "start_date": start_date,
                    "end_date": end_date,
                    "chunks": chunks,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                }
            for key in totals:
                totals[key] += result[key]
            chunk = {
                "start_date": chunk_start_text,
                "end_date": chunk_end_text,
                "status": "ok",
                "added": result["added"],
                "updated": result["updated"],
                "skipped": result["skipped"],
            }
            bad_records = result.get("bad_records")
            if bad_records:
                chunk["bad_records"] = bad_records
            chunks.append(chunk)
            cursor = chunk_end + timedelta(days=1)

        return {
            "status": "ok",
            "data_type": data_type,
            **totals,
            "start_date": start_date,
            "end_date": end_date,
            "chunks": chunks,
        }

    # 数据类型 -> (adapter 迭代方法, 入库方法, 水位时间字段)
    _SYNC_TARGETS = {
        "daily_activity": ("iter_daily_activity", "insert_daily_activity", "collected_at"),
        "sleep": ("iter_sleep_sessions", "insert_sleep_session", "start_at"),
        "workouts": ("iter_workouts", "insert_workout", "start_at"),
        "body_measurements": (
            "iter_body_measurements",
            "insert_body_measurement",
            "timestamp",
        ),
        "heart_rate": ("iter_heart_rate", "insert_heart_rate_sample", "timestamp"),
        "spo2": ("iter_spo2", "insert_spo2_sample", "timestamp"),
        "stress": ("iter_stress", "insert_stress_sample", "timestamp"),
        "abnormal_heart_beat": (
            "iter_abnormal_heart_beat",
            "insert_abnormal_heart_beat_event",
            "start_at",
        ),
    }

    # 每个 range 最多带回的坏记录条数，避免异常结果无限膨胀。
    _MAX_BAD_RECORDS = 20

    async def _sync_workout_detail_range(
        self, start_date: str, end_date: str, force_full: bool = False
    ) -> dict:
        """按 workouts 缓存逐次拉取 FDS 明细（秒级样本 + GPS 轨迹）。

        与 _SYNC_TARGETS 不同：数据源不是日期范围拉取，而是本地 workouts 表
        中已带 FDS 元数据的记录，逐次下载、幂等 upsert。默认跳过已入库明细
        的运动（默认全量同步才会纳入本类型，增量代价≈0）；force_full 重拉。
        """
        user_id = getattr(self.adapter, "get_user_id", lambda: None)() or "unknown"
        workouts = self.db.query_workouts(user_id, start_date, end_date)

        added = 0
        updated = 0
        skipped = 0
        attempted = 0
        bad_records: list[dict] = []
        for workout in workouts:
            workout_id = workout.get("workout_id")
            if not (workout.get("fds_sid") and workout.get("report_time")):
                skipped += 1  # FDS 元数据缺失的旧记录
                continue
            if not force_full:
                sample_count, gps_count = self.db.workout_detail_counts(user_id, str(workout_id))
                if sample_count or gps_count:
                    logger.debug("Workout detail for %s already cached, skipping", workout_id)
                    skipped += 1
                    continue
            attempted += 1
            try:
                samples, gps_points = await self.adapter.fetch_workout_detail(workout)
            except NotImplementedError:
                raise RuntimeError("Adapter does not support workout detail download") from None
            except Exception as exc:
                skipped += 1
                if len(bad_records) < self._MAX_BAD_RECORDS:
                    bad_records.append(
                        {
                            "data_type": "workout_detail",
                            "record_id": str(workout_id or "unknown"),
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:200],
                        }
                    )
                logger.warning(
                    "Workout detail failed for %s: %s: %s",
                    workout_id,
                    type(exc).__name__,
                    exc,
                )
                continue
            sample_added, sample_updated = self.db.insert_workout_detail_samples(samples)
            gps_added, gps_updated = self.db.insert_workout_gps_points(gps_points)
            added += sample_added + gps_added
            updated += sample_updated + gps_updated
            logger.info(
                "Workout detail %s: %d samples (%d new), %d gps points (%d new)",
                workout.get("workout_id"),
                len(samples),
                sample_added,
                len(gps_points),
                gps_added,
            )

        # 明细的覆盖判定靠逐运动存在性检查（不走水位），这里只记录
        # last_sync_at 供连接状态展示。
        try:
            self.db.update_sync_state("workout_detail")
        except Exception:
            logger.debug("Failed to record workout_detail sync state", exc_info=True)

        # Surface any failed workout rather than presenting mixed success as ok.
        status = "partial" if attempted > 0 and bad_records else "ok"
        return {
            "status": status,
            "data_type": "workout_detail",
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "bad_records": bad_records,
            "start_date": start_date,
            "end_date": end_date,
        }

    async def _sync_range(self, data_type: str, start_date: str, end_date: str) -> dict:
        target = self._SYNC_TARGETS.get(data_type)
        if target is None:
            raise ValueError(f"Unknown data type: {data_type}")
        iter_name, insert_name, ts_attr = target

        records = getattr(self.adapter, iter_name)(start_date, end_date)
        insert = getattr(self.db, insert_name)

        added = 0
        updated = 0
        skipped = 0
        last_ts = None
        bad_records: list[dict] = []

        async for record in self._iterate_records(records):
            # 逐记录隔离：单条坏记录（入库/字段异常）只计入 skipped，
            # 不中断本 range 的其余记录，也不卡住水位。
            try:
                inserted = insert(record)
                record_ts = getattr(record, ts_attr, None)
            except Exception as exc:
                skipped += 1
                if len(bad_records) < self._MAX_BAD_RECORDS:
                    # 只记可识别键与异常类型，错误文本截断，不落敏感值全文。
                    bad_records.append(
                        {
                            "data_type": data_type,
                            "record_id": str(getattr(record, "id", None) or "unknown"),
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:200],
                        }
                    )
                logger.warning(
                    "Skipping bad %s record %s: %s: %s",
                    data_type,
                    getattr(record, "id", None),
                    type(exc).__name__,
                    exc,
                )
                continue
            if inserted:
                added += 1
            else:
                updated += 1
            if record_ts is not None and (last_ts is None or record_ts > last_ts):
                last_ts = record_ts

        # 更新同步状态：水位只取成功记录的时间，坏记录不能卡住水位。
        if last_ts:
            self.db.update_sync_state(data_type, last_ts)

        logger.info(
            f"Synced {data_type}: {added} added, {updated} updated, "
            f"{skipped} skipped, range {start_date} to {end_date}"
        )

        return {
            "data_type": data_type,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "bad_records": bad_records,
            "start_date": start_date,
            "end_date": end_date,
        }

    def sync_data_type_sync(
        self,
        data_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        force_full: bool = False,
    ) -> dict:
        """Synchronous wrapper for sync_data_type.

        Use this when calling from synchronous code.
        """
        return asyncio.run(self.sync_data_type(data_type, start_date, end_date, force_full))
