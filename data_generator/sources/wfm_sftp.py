"""Source 4: exports from the WFM planning tool, delivered to the SFTP server.

- ``wfm/forecasts/FCST_<YYYYMMDD>.csv``: published every Monday at 07:00 UTC, the expected new
  cases and handle time per case type for the next 28 days. Each week is a new version, so
  actuals must be compared with the version that was current at the time.
- ``wfm/schedules/SCH_<week start>_v<n>.csv``: every person's planned day, segment by segment,
  in site-local time (the file carries the site, not the time zone). Version 1 is published on
  the Thursday before the week; version 2 follows on the Monday if leave or training was added
  since. Changes made later in the week are never re-published, as in real WFM practice.
- ``wfm/remediation/REMPLAN_<project>_v<n>.csv``: the weekly plan of each remediation project,
  published a week before it starts and re-planned once half-way through.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from ..config import GeneratorConfig
from ..master import MasterData, planned_day
from ..reference import CASE_TYPES
from ..rng import rng_for
from ..simulation import expected_arrivals, remediation_tranches
from .common import write_csv

FORECAST_COLUMNS = [
    "forecast_version",
    "forecast_date",
    "case_type_code",
    "forecast_cases",
    "forecast_aht_minutes",
]
SCHEDULE_COLUMNS = [
    "schedule_week_start",
    "schedule_version",
    "published_at",
    "employee_id",
    "site_code",
    "schedule_date",
    "activity",
    "start_local",
    "end_local",
]
REMPLAN_COLUMNS = [
    "project_id",
    "project_name",
    "plan_version",
    "published_on",
    "deadline",
    "scope_cases",
    "week_start",
    "planned_release",
    "planned_completions",
    "planned_fte",
]
FORECAST_DAYS = 28
PRODUCTIVE_MINUTES_PER_FTE_DAY = 390


def _at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=UTC)


def forecast_publications(cfg: GeneratorConfig) -> list[date]:
    first = cfg.start_date - timedelta(days=cfg.start_date.weekday())
    return [first + timedelta(days=7 * i) for i in range(cfg.horizon_days // 7 + 2)]


def forecast_rows(cfg: GeneratorConfig, md: MasterData, published: date):
    for offset in range(FORECAST_DAYS):
        day = published + timedelta(days=offset)
        for code, spec in CASE_TYPES.items():
            rng = rng_for(cfg.seed, "forecast", published, code, day)
            expected = expected_arrivals(cfg, md, code, day)
            # Forecasts further out are less accurate.
            noise = 0.04 + 0.004 * offset
            yield {
                "forecast_version": published,
                "forecast_date": day,
                "case_type_code": code,
                "forecast_cases": max(0, round(expected * (1 + rng.gauss(0, noise))))
                if code != "REM"
                else expected,
                "forecast_aht_minutes": round(spec["aht"] * (1 + rng.gauss(0, 0.05)), 1),
            }


def schedule_versions(cfg: GeneratorConfig) -> list[tuple[date, int, date]]:
    """(week start, version, publish date) for every schedule export in the horizon."""
    first = cfg.start_date - timedelta(days=cfg.start_date.weekday())
    out = []
    for i in range(cfg.horizon_days // 7 + 1):
        week = first + timedelta(days=7 * i)
        out.append((week, 1, week - timedelta(days=4)))
        out.append((week, 2, week))
    return out


def schedule_rows(md: MasterData, week: date, known_on: date):
    for person in md.staff:
        for offset in range(7):
            day = week + timedelta(days=offset)
            plan = planned_day(md, person, day, known_on)
            for activity, start, end in plan or []:
                yield {
                    "employee_id": person["employee_id"],
                    "site_code": person["site_code"],
                    "schedule_date": day,
                    "activity": activity,
                    "start_local": start.strftime("%Y-%m-%d %H:%M"),
                    "end_local": end.strftime("%Y-%m-%d %H:%M"),
                }


def remediation_plan_rows(project: dict, version: int, published: date):
    """Weekly plan: tranche loads, and completions spread evenly up to the deadline week.

    Version 2 is a re-plan from the publish week: it assumes the first half ran 10% behind and
    spreads what is left over the remaining weeks, which raises the planned FTE.
    """
    weeks = []
    week = project["start_date"]
    while week <= project["deadline"]:
        weeks.append(week)
        week += timedelta(days=7)
    loads = dict(remediation_tranches(project))
    scope = project["scope_cases"]
    even = scope / len(weeks)
    if version == 1:
        plan = [even] * len(weeks)
    else:
        done = [n for n, w in enumerate(weeks) if w < published]
        behind = sum(even for _ in done) * 0.9
        left = [n for n, w in enumerate(weeks) if w >= published]
        plan = [even * 0.9 if n in done else (scope - behind) / max(len(left), 1) for n in range(len(weeks))]
    for week, planned in zip(weeks, plan, strict=True):
        completions = math.floor(planned)
        yield {
            "project_id": project["project_id"],
            "project_name": project["project_name"],
            "plan_version": version,
            "published_on": published,
            "deadline": project["deadline"],
            "scope_cases": scope,
            "week_start": week,
            "planned_release": loads.get(week, 0),
            "planned_completions": completions,
            "planned_fte": round(
                completions * CASE_TYPES["REM"]["aht"] / (PRODUCTIVE_MINUTES_PER_FTE_DAY * 5), 1
            ),
        }


def remediation_plan_versions(project: dict) -> list[tuple[int, date]]:
    halfway = project["start_date"] + (project["deadline"] - project["start_date"]) / 2
    return [(1, project["start_date"] - timedelta(days=7)), (2, halfway)]


def write_wfm_files(md: MasterData, out_dir: Path, as_of: datetime) -> dict[str, int]:
    cfg = md.cfg
    root = out_dir / "sftp" / "wfm"
    counts = {"forecast_files": 0, "schedule_files": 0, "remediation_plan_files": 0}

    for published in forecast_publications(cfg):
        if _at(published, 7) > as_of:
            break
        write_csv(
            root / "forecasts" / f"FCST_{published:%Y%m%d}.csv",
            FORECAST_COLUMNS,
            forecast_rows(cfg, md, published),
        )
        counts["forecast_files"] += 1

    for week, version, published in schedule_versions(cfg):
        at = _at(published, 10 if version == 1 else 8)
        if at > as_of:
            continue
        if version == 2 and list(schedule_rows(md, week, published)) == list(
            schedule_rows(md, week, published - timedelta(days=4))
        ):
            continue
        rows = [
            {"schedule_week_start": week, "schedule_version": version, "published_at": at, **row}
            for row in schedule_rows(md, week, published)
        ]
        write_csv(root / "schedules" / f"SCH_{week:%Y%m%d}_v{version}.csv", SCHEDULE_COLUMNS, rows)
        counts["schedule_files"] += 1

    for project in md.projects:
        for version, published in remediation_plan_versions(project):
            if _at(published, 8) > as_of:
                continue
            path = root / "remediation" / f"REMPLAN_{project['project_id']}_v{version}.csv"
            write_csv(path, REMPLAN_COLUMNS, remediation_plan_rows(project, version, published))
            counts["remediation_plan_files"] += 1
    return counts
