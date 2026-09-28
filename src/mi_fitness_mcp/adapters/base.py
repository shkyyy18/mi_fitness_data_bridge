"""Base adapter interface for data sources."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Coroutine, Iterator
from typing import Any, Union

from mi_fitness_mcp.models import (
    AbnormalHeartBeatEvent,
    BodyMeasurement,
    DailyActivity,
    HeartRateSample,
    SleepSession,
    SpO2Sample,
    StressSample,
    Workout,
)


class DataAdapter(ABC):
    """Abstract base class for data source adapters."""

    @abstractmethod
    def connect(self) -> Union[bool, "Coroutine[Any, Any, bool]"]:
        """Connect to data source.

        Returns:
            True if connection successful
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected to data source."""
        pass

    @abstractmethod
    def get_user_id(self) -> str | None:
        """Get user identifier from data source."""
        pass

    @abstractmethod
    def iter_daily_activity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[DailyActivity] | AsyncIterator[DailyActivity]:
        """Iterate over daily activity records."""
        pass

    @abstractmethod
    def iter_sleep_sessions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[SleepSession] | AsyncIterator[SleepSession]:
        """Iterate over sleep session records."""
        pass

    @abstractmethod
    def iter_workouts(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[Workout] | AsyncIterator[Workout]:
        """Iterate over workout records."""
        pass

    @abstractmethod
    def iter_body_measurements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[BodyMeasurement] | AsyncIterator[BodyMeasurement]:
        """Iterate over body measurement records."""
        pass

    @abstractmethod
    def iter_heart_rate(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[HeartRateSample] | AsyncIterator[HeartRateSample]:
        """Iterate over heart rate records."""
        pass

    @abstractmethod
    def iter_spo2(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[SpO2Sample] | AsyncIterator[SpO2Sample]:
        """Iterate over blood oxygen saturation records."""
        pass

    @abstractmethod
    def iter_stress(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[StressSample] | AsyncIterator[StressSample]:
        """Iterate over stress records."""
        pass

    @abstractmethod
    def iter_abnormal_heart_beat(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterator[AbnormalHeartBeatEvent] | AsyncIterator[AbnormalHeartBeatEvent]:
        """Iterate over abnormal heart beat events."""
        pass

    @abstractmethod
    def get_available_data_types(self) -> list[str]:
        """Get list of available data types."""
        pass

    async def fetch_workout_detail(self, workout: dict) -> tuple[list, list]:
        """Optional capability: download FDS per-second samples and GPS points.

        ``workout`` is one row of the workouts table. Returns
        ``(samples, gps_points)``; both empty when the adapter lacks the
        capability or the workout has no detail blob. See
        docs/workout-detail-feasibility.md.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support workout detail download")
