"""Simulated clock with configurable speed multiplier.

Advances simulated time relative to real time at a given rate:
  speed_multiplier=1.0  → real-time
  speed_multiplier=42.0 → 42 simulated seconds per real second
  speed_multiplier=0    → instant/legacy mode (time frozen at start)
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

# Default simulation start: Monday 9:00 AM UTC
_DEFAULT_START = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)


class SimulationClock:
    """Thread-safe simulated clock."""

    def __init__(
        self,
        speed_multiplier: float = 0,
        start_time: datetime | None = None,
    ) -> None:
        self._speed_multiplier = speed_multiplier
        self._start_sim = start_time or _DEFAULT_START
        self._start_real_mono = time.monotonic()
        self._manual_offset = timedelta(0)
        self._lock = threading.Lock()

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    def now(self) -> datetime:
        """Return current simulated time."""
        with self._lock:
            if self._speed_multiplier == 0:
                return self._start_sim + self._manual_offset
            elapsed_real = time.monotonic() - self._start_real_mono
            simulated_elapsed = timedelta(seconds=elapsed_real * self._speed_multiplier)
            return self._start_sim + simulated_elapsed + self._manual_offset

    def advance(self, duration: timedelta) -> None:
        """Manually advance the clock (for phase-based advancement)."""
        with self._lock:
            self._manual_offset += duration

    def elapsed(self) -> timedelta:
        """Total simulated time elapsed since start."""
        return self.now() - self._start_sim

    def simulated_day(self) -> int:
        """Which day of the simulation (1-indexed)."""
        return self.elapsed().days + 1

    def simulated_hour(self) -> int:
        """Current hour of the simulated day (0-23)."""
        return self.now().hour

    def monotonic(self) -> float:
        """Simulated monotonic time in seconds since start.

        Compatible with time.monotonic() interface for TriggerSystem.
        """
        return self.elapsed().total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Serializable state for DB storage."""
        return {
            "start_time": self._start_sim.isoformat(),
            "speed_multiplier": self._speed_multiplier,
            "elapsed_seconds": self.elapsed().total_seconds(),
            "current_simulated_time": self.now().isoformat(),
            "simulated_day": self.simulated_day(),
        }
