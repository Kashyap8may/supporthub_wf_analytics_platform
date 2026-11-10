"""Settings that control how much data is generated and for which dates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = 42
    start_date: date = date(2026, 7, 1)
    days: int = 90
    # Fixed calendar for hires, leavers, leave and project plans. These must not depend on
    # ``days``: a daily run adds one day, and that must never rewrite days already published.
    horizon_days: int = 365

    # Team sizes in reference.TEAMS are multiplied by this.
    staff_scale: float = 1.0

    # Mean new cases per business day before weekday and month-end effects.
    onboarding_per_day: float = 260
    edd_per_day: float = 30
    # Periodic refresh cases released on the first business day of each month.
    periodic_per_month: int = 3600

    # Share of records that get a deliberate data-quality problem (late or duplicate rows, etc.).
    dq_rate: float = 0.01

    def __post_init__(self) -> None:
        if self.days > self.horizon_days:
            raise ValueError(f"days ({self.days}) cannot exceed horizon_days ({self.horizon_days})")

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.days - 1)

    @property
    def horizon_end(self) -> date:
        return self.start_date + timedelta(days=self.horizon_days - 1)

    def dates(self) -> list[date]:
        return [self.start_date + timedelta(days=i) for i in range(self.days)]

    def scaled(self, factor: float) -> GeneratorConfig:
        """Return a copy with staff and volumes multiplied by ``factor``."""
        return replace(
            self,
            staff_scale=self.staff_scale * factor,
            onboarding_per_day=self.onboarding_per_day * factor,
            edd_per_day=self.edd_per_day * factor,
            periodic_per_month=round(self.periodic_per_month * factor),
        )
