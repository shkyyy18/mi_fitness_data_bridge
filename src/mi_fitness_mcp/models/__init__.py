"""Pydantic models for Mi Fitness MCP."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BaseEntity(BaseModel):
    """Base entity with common fields."""

    id: str = Field(description="Internal UUID")
    provider: Literal["mi_fitness"] = Field(description="Data provider")
    source_type: Literal["cloud_session"] = Field(description="Source of the data")
    source_record_id: str | None = Field(None, description="Provider's native ID")
    user_id: str = Field(description="User identifier")
    device_id: str | None = Field(None, description="Device that recorded the data")
    timezone: str = Field(default="UTC", description="Timezone for the data")
    collected_at: datetime | None = Field(None, description="When data was recorded")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class DailyActivity(BaseEntity):
    """Daily activity summary (steps, calories, etc.)."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    steps: int = Field(ge=0, description="Number of steps")
    distance_m: float = Field(ge=0, description="Distance in meters")
    active_kcal: float = Field(ge=0, description="Active calories burned")
    total_kcal: float | None = Field(None, ge=0, description="Total calories")
    floors: int | None = Field(None, ge=0, description="Floors climbed")
    active_minutes: int | None = Field(None, ge=0, description="Active minutes")


class SleepStage(BaseModel):
    """Sleep stage information."""

    stage: Literal["deep", "light", "rem", "awake"] = Field(description="Sleep stage")
    minutes: int = Field(ge=0, description="Duration in minutes")


class SleepSession(BaseEntity):
    """Sleep session data."""

    sleep_id: str = Field(description="Unique sleep session ID")
    start_at: datetime = Field(description="Sleep start time")
    end_at: datetime = Field(description="Sleep end time")
    duration_minutes: int = Field(ge=0, description="Total duration")
    time_asleep_minutes: int = Field(ge=0, description="Actual sleep time")
    time_awake_minutes: int = Field(ge=0, description="Time awake during sleep")
    sleep_score: int | None = Field(None, ge=0, le=100, description="Sleep quality score")
    sleep_score_source: Literal["sleep_record", "daily_report"] | None = Field(
        None, description="Upstream score origin; daily_report is assigned to main sleep only"
    )
    is_nap: bool = Field(default=False, description="Whether this is a nap")
    stages: list[SleepStage] = Field(default_factory=list, description="Sleep stages breakdown")


class Workout(BaseEntity):
    """Workout/exercise session."""

    workout_id: str = Field(description="Unique workout ID")
    activity_type: str = Field(description="Type of activity (running, cycling, etc.)")
    start_at: datetime = Field(description="Workout start time")
    end_at: datetime = Field(description="Workout end time")
    duration_minutes: int = Field(ge=0, description="Duration in minutes")
    distance_m: float | None = Field(None, ge=0, description="Distance in meters")
    calories_kcal: float | None = Field(None, ge=0, description="Calories burned")
    avg_heart_rate_bpm: int | None = Field(None, ge=0, description="Average heart rate")
    max_heart_rate_bpm: int | None = Field(None, ge=0, description="Maximum heart rate")
    avg_pace_sec_per_km: float | None = Field(None, ge=0, description="Average pace")
    max_pace_sec_per_km: float | None = Field(None, ge=0, description="Maximum pace")
    total_steps: int | None = Field(None, ge=0, description="Steps during workout")
    # 运动报告补充汇总（upstream SportBasicReport；随设备/固件可能缺失）
    min_heart_rate_bpm: int | None = Field(None, ge=0, description="Minimum heart rate")
    valid_duration_seconds: int | None = Field(
        None, ge=0, description="Active duration excluding pauses, as reported"
    )
    avg_cadence: int | None = Field(None, ge=0, description="Average step cadence (spm)")
    max_cadence: int | None = Field(None, ge=0, description="Maximum step cadence (spm)")
    avg_stride: int | None = Field(None, ge=0, description="Average stride, as reported")
    avg_speed_mps: float | None = Field(None, ge=0, description="Average speed in m/s")
    min_pace_sec_per_km: float | None = Field(None, ge=0, description="Minimum pace")
    avg_height_m: float | None = Field(None, description="Average altitude in meters")
    max_height_m: float | None = Field(None, description="Maximum altitude in meters")
    min_height_m: float | None = Field(None, description="Minimum altitude in meters")
    rise_height_m: float | None = Field(None, ge=0, description="Total elevation gain in meters")
    fall_height_m: float | None = Field(None, ge=0, description="Total elevation loss in meters")
    total_climbing_m: float | None = Field(
        None, ge=0, description="Total climbing as reported, in meters"
    )
    vo2max: int | None = Field(None, ge=0, description="VO2max estimate")
    train_effect: float | None = Field(None, ge=0, description="Aerobic training effect")
    anaerobic_train_effect: float | None = Field(
        None, ge=0, description="Anaerobic training effect"
    )
    training_load: int | None = Field(None, ge=0, description="Training load")
    recovery_time: int | None = Field(
        None, ge=0, description="Recovery time as reported by upstream (unit unverified)"
    )
    avg_spo2_pct: int | None = Field(None, ge=0, le=100, description="Average SpO2 percentage")
    # FDS 明细数据定位元数据（拉取秒级记录/GPS 轨迹所需的 blob 寻址字段）
    fds_sid: str | None = Field(None, description="Upstream sid used to locate FDS detail blobs")
    proto_type: int | None = Field(
        None, ge=0, description="Binary protocol type used for FDS parser dispatch"
    )
    report_version: int | None = Field(
        None, ge=0, description="Sport report version; <=0 means no detail blob exists"
    )
    report_time: int | None = Field(
        None,
        ge=0,
        description="Report-level unix timestamp (seconds) used in the FDS data ID",
    )
    tz_in_15min: int | None = Field(
        None, description="Report timezone offset in 15-minute increments"
    )


class WorkoutSample(BaseEntity):
    """Per-second workout sample parsed from the FDS binary record blob."""

    workout_id: str = Field(description="Provider workout ID this sample belongs to")
    offset_seconds: int = Field(
        description="Seconds since workout start; may be slightly negative when the "
        "device blob timestamps precede the cloud-reported start (e.g. early GPS lock)"
    )
    timestamp: datetime = Field(description="Absolute sample time")
    heart_rate_bpm: int | None = Field(None, ge=0, description="Heart rate in bpm")
    calories_kcal: float | None = Field(None, ge=0, description="Calories, as reported")
    distance_m: float | None = Field(None, ge=0, description="Distance in meters")
    steps: int | None = Field(None, ge=0, description="Cumulative steps, when reported")
    cadence: int | None = Field(None, ge=0, description="Step cadence in spm, when reported")
    pace_sec_per_km: float | None = Field(None, ge=0, description="Pace in s/km, when reported")
    speed_mps: float | None = Field(None, ge=0, description="Speed in m/s, when reported")
    altitude_m: float | None = Field(None, description="Altitude in meters, when reported")


class GpsPoint(BaseEntity):
    """Single GPS track point parsed from the FDS GPS blob."""

    workout_id: str = Field(description="Provider workout ID this point belongs to")
    offset_seconds: int = Field(
        description="Seconds since workout start; may be slightly negative when the "
        "device blob timestamps precede the cloud-reported start (e.g. early GPS lock)"
    )
    timestamp: datetime = Field(description="Absolute point time")
    latitude: float = Field(ge=-90, le=90, description="GPS latitude")
    longitude: float = Field(ge=-180, le=180, description="GPS longitude")
    accuracy: float | None = Field(None, ge=0, description="GPS accuracy")
    speed_mps: float | None = Field(None, ge=0, description="GPS speed in m/s")
    gps_source: int | None = Field(None, ge=0, description="GPS source indicator")
    altitude_m: float | None = Field(None, description="GPS altitude in meters")
    hdop: float | None = Field(None, ge=0, description="Horizontal dilution of precision")


class BodyMeasurement(BaseEntity):
    """Body composition measurement (from smart scale)."""

    timestamp: datetime = Field(description="Measurement time")
    weight_kg: float = Field(gt=0, description="Weight in kilograms")
    bmi: float | None = Field(None, gt=0, description="Body mass index")
    body_fat_pct: float | None = Field(None, ge=0, le=100, description="Body fat percentage")
    muscle_mass_kg: float | None = Field(None, ge=0, description="Muscle mass")
    water_pct: float | None = Field(None, ge=0, le=100, description="Body water percentage")
    bone_mass_kg: float | None = Field(None, ge=0, description="Bone mass")
    visceral_fat_score: int | None = Field(None, ge=0, description="Visceral fat level")
    basal_metabolism_kcal: int | None = Field(None, ge=0, description="BMR in kcal")
    metabolic_age: int | None = Field(None, ge=0, description="Metabolic age")


class HeartRateSample(BaseEntity):
    """Heart rate measurement."""

    timestamp: datetime = Field(description="Measurement time")
    bpm: int = Field(ge=0, description="Heart rate in beats per minute")
    sample_type: Literal["resting", "active", "passive", "workout"] = Field(
        default="passive", description="Type of measurement"
    )


class SpO2Sample(BaseEntity):
    """Blood oxygen saturation measurement."""

    timestamp: datetime = Field(description="Measurement time")
    spo2_pct: int = Field(ge=0, le=100, description="SpO2 percentage")


class StressSample(BaseEntity):
    """Stress level measurement."""

    timestamp: datetime = Field(description="Measurement time")
    stress_score: int = Field(ge=0, le=100, description="Stress score")
    level: Literal["low", "medium", "high"] = Field(description="Stress level category")


class AbnormalHeartBeatEvent(BaseEntity):
    """Abnormal heart beat event."""

    event_id: str = Field(description="Unique abnormal heart beat event ID")
    start_at: datetime = Field(description="Event start time")
    end_at: datetime = Field(description="Event end time")
    duration_seconds: int = Field(ge=0, description="Event duration in seconds")


class UserProfile(BaseModel):
    """User profile information."""

    user_id: str = Field(description="User identifier")
    display_name: str | None = Field(None, description="Display name")
    birth_year: int | None = Field(None, description="Birth year")
    sex: Literal["male", "female", "other"] | None = Field(None, description="Sex")
    height_cm: float | None = Field(None, gt=0, description="Height in cm")
    timezone: str = Field(default="UTC", description="User timezone")
    devices: list[dict[str, Any]] = Field(default_factory=list, description="Connected devices")


class DeviceInfo(BaseModel):
    """Connected device information."""

    device_id: str = Field(description="Device identifier")
    device_type: str = Field(description="Type (band, watch, scale)")
    model: str = Field(description="Device model")
    firmware_version: str | None = Field(None, description="Firmware version")
    last_sync_at: datetime | None = Field(None, description="Last sync time")


class DataCoverage(BaseModel):
    """Data coverage information for a metric."""

    data_type: str = Field(description="Type of data")
    first_date: str | None = Field(None, description="First date with data")
    last_date: str | None = Field(None, description="Last date with data")
    days_with_data: int = Field(ge=0, description="Number of days with data")
    gaps_detected: list[tuple[str, str]] = Field(
        default_factory=list, description="Detected date gaps"
    )


class ConnectionStatus(BaseModel):
    """Connection status response."""

    mode: Literal["mi_fitness_cloud", "not_configured"]
    connected: bool
    last_sync_at: datetime | None = None
    available_data_types: list[str] = Field(default_factory=list)
    account_id_masked: str | None = None
    sync_health: Literal["healthy", "stale", "error", "unknown"] = "unknown"
    next_action: str | None = None
    message: str | None = None


class SyncResult(BaseModel):
    """Data synchronization result."""

    sync_id: str = Field(description="Unique sync identifier")
    started_at: datetime = Field(description="Sync start time")
    finished_at: datetime = Field(description="Sync end time")
    records_added: int = Field(ge=0, description="New records added")
    records_updated: int = Field(ge=0, description="Records updated")
    records_skipped: int = Field(ge=0, description="Records skipped (duplicates)")
    data_types_synced: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """Generic query response envelope."""

    status: Literal["ok", "error"] = "ok"
    source: Literal["mi_fitness_cloud", "cloud_session", "cache", "unknown"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    timezone: str = "UTC"
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
