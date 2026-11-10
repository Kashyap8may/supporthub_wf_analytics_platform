"""Source 3: HR and quality files dropped into S3.

- ``hr/roster/extract_date=YYYY-MM-DD/roster.csv``: the HR system's full daily snapshot, taken at
  02:00 UTC. Staff appear on their hire date; leavers stay listed as LEAVER for 30 days.
  Team moves only show up as a changed ``team_id`` from one snapshot to the next.
- ``qc/results/date=YYYY-MM-DD/qc_results.jsonl``: the QC tool's daily export at 23:00 UTC.
  QC samples cases, so most cases have no result; about 5% of results miss the day's export
  and land in the next day's file.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from ..master import MasterData, employed_on, manager_of, team_on
from ..reference import SITES, TEAMS
from ..rng import rng_for
from ..simulation import SimulationResult
from .common import write_csv, write_jsonl

ROSTER_COLUMNS = [
    "extract_date",
    "employee_id",
    "network_login",
    "first_name",
    "last_name",
    "email",
    "site_code",
    "site_name",
    "team_id",
    "team_name",
    "role",
    "manager_employee_id",
    "hire_date",
    "leave_date",
    "employment_status",
    "fte",
]

ROSTER_HOUR = 2
QC_EXPORT_HOUR = 23


def roster_rows(md: MasterData, extract_date: date):
    for person in md.staff:
        if person["hire_date"] > extract_date:
            continue
        left = person["leave_date"]
        if left is not None and extract_date >= left + timedelta(days=30):
            continue
        team = team_on(person, min(extract_date, left - timedelta(days=1)) if left else extract_date)
        yield {
            **person,
            "extract_date": extract_date,
            "site_name": SITES[person["site_code"]]["name"],
            "team_id": team,
            "team_name": TEAMS[team][0],
            "manager_employee_id": manager_of(person, extract_date),
            "leave_date": left if left is not None and left <= extract_date + timedelta(days=30) else None,
            "employment_status": "ACTIVE" if employed_on(person, extract_date) else "LEAVER",
        }


def write_roster(md: MasterData, out_dir: Path, as_of: datetime, first: date) -> dict[str, int]:
    files = rows = 0
    d = first
    while datetime.combine(d, time(ROSTER_HOUR), tzinfo=UTC) <= as_of:
        path = out_dir / "s3" / "hr" / "roster" / f"extract_date={d.isoformat()}" / "roster.csv"
        rows += write_csv(path, ROSTER_COLUMNS, roster_rows(md, d))
        files += 1
        d += timedelta(days=1)
    return {"roster_files": files, "roster_rows": rows}


def qc_landing_date(seed: int, result: dict) -> date:
    late = rng_for(seed, "qc-late", result["qc_id"]).random() < 0.05
    return result["checked_at"].date() + timedelta(days=1 if late else 0)


def write_qc_results(md: MasterData, sim: SimulationResult, out_dir: Path, as_of: datetime) -> dict[str, int]:
    by_day: dict[date, list[dict]] = defaultdict(list)
    for result in sim.qc_results:
        by_day[qc_landing_date(md.cfg.seed, result)].append(result)
    files = rows = 0
    for day in sorted(by_day):
        if datetime.combine(day, time(QC_EXPORT_HOUR), tzinfo=UTC) > as_of:
            continue
        path = out_dir / "s3" / "qc" / "results" / f"date={day.isoformat()}" / "qc_results.jsonl"
        rows += write_jsonl(path, sorted(by_day[day], key=lambda r: r["qc_id"]))
        files += 1
    return {"qc_files": files, "qc_results": rows}
