"""Split one simulated year into what each source receives, day by day.

    python -m data_generator.daily --out output/daily              # 365 days from 2026-07-01
    python -m data_generator.daily --out output/daily --scale 0.1 --days 14

Writes one folder per UTC day. Day D holds what changed in the sources during D, as it looked
at the end of D (midnight UTC that night), so applying the days in order rebuilds each source
exactly as ``generate`` shows it. The first folder is the day before the simulation starts and
holds the opening state (reference data, staff already employed, early WFM publications).

    <day>/casedesk/<table>.csv          rows inserted or updated during the day (upsert by key)
    <day>/activity_api/segments.jsonl   activity segments that started or ended (put by segment_id)
    <day>/s3/...                        files that land in the S3 drop that day
    <day>/sftp/...                      files that arrive on the SFTP server that day

``data_generator.publish`` reads these folders from S3 and applies them to the live sources.
"""

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import GeneratorConfig
from .master import MasterData, build_master
from .simulate import end_of
from .simulation import SimulationResult, simulate
from .sources.activity_api import recorded_end, segment_document, upper_case_logins
from .sources.casedesk import (
    TABLE_COLUMNS,
    case_row,
    project_row,
    recorded_events,
    static_tables,
    user_changes,
    user_row,
)
from .sources.common import write_csv, write_jsonl
from .sources.s3_drops import write_qc_results, write_roster
from .sources.wfm_sftp import remediation_plan_versions, write_wfm_files


def day_of(ts: datetime) -> date:
    # A change exactly at midnight is already visible at end_of(previous day).
    return (ts - timedelta(microseconds=1)).date()


def casedesk_changes(cfg: GeneratorConfig, md: MasterData, sim: SimulationResult) -> dict[date, dict]:
    opening = cfg.start_date - timedelta(days=1)

    def bucket(ts: datetime) -> date:
        return max(day_of(ts), opening)

    days: dict[date, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for table, rows in static_tables().items():
        days[opening][table] = rows
    for project in md.projects:
        row = project_row(project)
        days[bucket(row["created_at"])]["remediation_projects"].append(row)
    for person in md.staff:
        for changed in user_changes(person):
            day = bucket(changed)
            days[day]["users"].append(user_row(person, end_of(day)))

    by_case: dict[int, list[dict]] = defaultdict(list)
    for ev in sim.events:
        by_case[ev["case_id"]].append(ev)
    for case in sim.cases:
        events = sorted(by_case[case["case_id"]], key=lambda e: (e["event_ts"], e["seq"]))
        # One row per day the case changed, showing it as at the end of that day.
        for n, ev in enumerate(events):
            day = bucket(ev["event_ts"])
            if n + 1 == len(events) or bucket(events[n + 1]["event_ts"]) != day:
                days[day]["cases"].append(case_row(case, events[: n + 1]))

    for row in recorded_events(cfg.seed, sim.events):
        days[bucket(row["recorded_at"])]["case_events"].append(row)
    for tables in days.values():
        tables.get("users", []).sort(key=lambda r: r["employee_id"])
        tables.get("cases", []).sort(key=lambda r: r["case_id"])
    return days


def segment_changes(cfg: GeneratorConfig, md: MasterData, sim: SimulationResult) -> dict[date, list[dict]]:
    upper = upper_case_logins(md)
    days: dict[date, list[dict]] = defaultdict(list)
    for seg in sim.activities:
        changed = {day_of(seg["start_ts"])}
        end = recorded_end(cfg.seed, seg)
        if end is not None:
            changed.add(day_of(end))
        for day in sorted(changed):
            days[day].append(segment_document(md, seg, upper, end_of(day)))
    return days


# Which day a file arrives, read from its path. Schedules and remediation plans carry a version,
# and their publish day is worked out from the name.
_DATED = [
    re.compile(r"^s3/hr/roster/extract_date=(\d{4}-\d{2}-\d{2})/"),
    re.compile(r"^s3/qc/results/date=(\d{4}-\d{2}-\d{2})/"),
    re.compile(r"^sftp/wfm/forecasts/FCST_(\d{8})\.csv$"),
]
_SCHEDULE = re.compile(r"^sftp/wfm/schedules/SCH_(\d{8})_v(\d)\.csv$")
_REMPLAN = re.compile(r"^sftp/wfm/remediation/REMPLAN_([\w-]+)_v(\d)\.csv$")


def _date(text: str) -> date:
    text = text.replace("-", "")
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def file_day(md: MasterData, rel_path: str) -> date:
    for pattern in _DATED:
        match = pattern.match(rel_path)
        if match:
            return _date(match.group(1))
    match = _SCHEDULE.match(rel_path)
    if match:
        week = _date(match.group(1))
        return week - timedelta(days=4) if match.group(2) == "1" else week
    match = _REMPLAN.match(rel_path)
    if match:
        project = next(p for p in md.projects if p["project_id"] == match.group(1))
        return dict(remediation_plan_versions(project))[int(match.group(2))]
    raise ValueError(f"no arrival day for {rel_path}")


def write_daily(cfg: GeneratorConfig, out_dir: Path) -> dict[str, int]:
    md = build_master(cfg)
    sim = simulate(cfg, md)
    opening, last_day = cfg.start_date - timedelta(days=1), cfg.end_date
    counts: dict[str, int] = defaultdict(int)

    for day, tables in casedesk_changes(cfg, md, sim).items():
        if day > last_day:
            continue
        for table, rows in tables.items():
            counts[f"casedesk_{table}_rows"] += write_csv(
                out_dir / day.isoformat() / "casedesk" / f"{table}.csv", TABLE_COLUMNS[table], rows
            )

    for day, docs in segment_changes(cfg, md, sim).items():
        if day <= last_day:
            counts["segment_documents"] += write_jsonl(
                out_dir / day.isoformat() / "activity_api" / "segments.jsonl", docs
            )

    # The file writers already date every file; write them all, then move each into its day.
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        as_of = end_of(last_day)
        write_roster(md, staging, as_of, first=cfg.start_date)
        write_qc_results(md, sim, staging, as_of)
        write_wfm_files(md, staging, as_of)
        for path in sorted(p for p in staging.rglob("*") if p.is_file()):
            rel = path.relative_to(staging).as_posix()
            day = max(file_day(md, rel), opening)
            target = out_dir / day.isoformat() / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, target)
            counts["files"] += 1

    counts["days"] = len([p for p in out_dir.iterdir() if p.is_dir()])
    return dict(counts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Split the simulated year into daily source changes.")
    parser.add_argument("--out", type=Path, default=Path("output/daily"), help="output folder (replaced)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-date", type=date.fromisoformat, default=GeneratorConfig.start_date)
    parser.add_argument("--days", type=int, default=GeneratorConfig.horizon_days)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args(argv)

    cfg = GeneratorConfig(seed=args.seed, start_date=args.start_date, days=args.days)
    if args.scale != 1.0:
        cfg = cfg.scaled(args.scale)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    started = time.perf_counter()
    counts = write_daily(cfg, args.out)
    print(f"Wrote {counts['days']} day folders into {args.out}/ in {time.perf_counter() - started:.0f}s")
    for name, n in sorted(counts.items()):
        print(f"  {name:<34} {n:>10,}")


if __name__ == "__main__":
    main()
