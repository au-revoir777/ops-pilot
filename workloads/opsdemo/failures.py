"""Controlled, non-destructive failure injection.

Nothing here touches real infrastructure: failures are added latency, simulated
database slowness, or synthetic HTTP 500s inside the workload process. All
randomness comes from one seedable RNG so an incident can be replayed exactly.
"""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass


class FailureMode(enum.StrEnum):
    NONE = "none"
    LATENCY = "latency"  # every business request is slowed down
    ERRORS = "errors"  # a fraction of business requests fail with HTTP 500
    DB = "db"  # the (simulated) database becomes slow


class FailureInjectionDisabled(Exception):
    """Raised when someone tries to change the mode while injection is disabled."""


@dataclass(frozen=True)
class FailureProfile:
    latency_ms: int = 2000
    db_latency_ms: int = 900
    error_rate: float = 0.5
    jitter: float = 0.2  # +/- 20% so injected latency looks like a distribution


class FailureInjector:
    def __init__(
        self,
        *,
        enabled: bool,
        mode: FailureMode = FailureMode.NONE,
        profile: FailureProfile | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.enabled = enabled
        self.profile = profile or FailureProfile()
        self.rng = rng or random.Random()  # noqa: S311 - simulation, not security
        # A configured mode is ignored unless injection is explicitly enabled.
        self._mode = mode if enabled else FailureMode.NONE

    @property
    def mode(self) -> FailureMode:
        return self._mode

    def set_mode(self, mode: FailureMode) -> None:
        if not self.enabled:
            raise FailureInjectionDisabled("Failure injection is disabled")
        self._mode = mode

    def _jittered(self, base_ms: int) -> float:
        factor = self.rng.uniform(1 - self.profile.jitter, 1 + self.profile.jitter)
        return base_ms * factor / 1000

    def request_delay_seconds(self) -> float:
        if self._mode is FailureMode.LATENCY:
            return self._jittered(self.profile.latency_ms)
        return 0.0

    def should_fail_request(self) -> bool:
        return self._mode is FailureMode.ERRORS and self.rng.random() < self.profile.error_rate

    def db_delay_seconds(self) -> float:
        if self._mode is FailureMode.DB:
            return self._jittered(self.profile.db_latency_ms)
        return 0.0
