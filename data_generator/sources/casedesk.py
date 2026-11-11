"""Source 1: the CaseDesk case management database (RDS PostgreSQL).

Writes one CSV per table showing the database as it looks at ``as_of``. ``cases`` holds each
case's current state, updated in place; ``case_events`` is the append-only status history.

Data problems carried over from real case tools:
- The audit trail lags: about 2% of events are written to ``case_events`` hours after they
  happened (``recorded_at`` later than ``event_ts``), so ``cases`` can be ahead of the history.
- About 0.5% of events are written twice: same ``event_id``, a second row a few minutes later.
- ``due_at`` is CaseDesk's naive due date (calendar days, no holidays, no pauses); the real
  SLA counts business days at the working site and stops while pending customer information.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from ..master import MasterData
from ..reference import CASE_TYPES, QUEUES
from ..rng import rng_for
from ..simulation import SimulationResult
from .common import write_csv

TABLE_COLUMNS = {
    "case_types": ["case_type_code", "case_type_name", "queue_code", "sla_days", "created_at", "updated_at"],
    "queues": ["queue_code", "queue_name", "case_type_code", "created_at", "updated_at"],
    "users": ["employee_id", "display_name", "email", "is_active", "created_at", "updated_at"],
    "remediation_projects": [
        "project_id",
        "project_name",
        "start_date",
        "deadline",
        "scope_cases",
        "created_at",
        "updated_at",
    ],
    "cases": [
        "case_id",
        "case_ref",
        "case_type_code",
        "queue_code",
        "remediation_project_id",
        "customer_ref",
        "customer_segment",
        "risk_tier",
        "priority",
        "status",
        "assignee_employee_id",
        "created_at",
        "due_at",
        "closed_at",
        "outcome",
        "updated_at",
    ],
    "case_events": [
        "event_row_id",
        "event_id",
        "case_id",
        "event_type",
        "from_status",
        "to_status",
        "assignee_employee_id",
        "actor_employee_id",
        "outcome",
        "event_ts",
        "recorded_at",
    ],
}

# Tables in an order that satisfies foreign keys.
LOAD_ORDER = list(TABLE_COLUMNS)

SYSTEM_START = datetime(2025, 1, 6, 8, 0, tzinfo=UTC)


def _at(day: date, hour: int = 8) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=UTC)


def recorded_events(seed: int, events: list[dict]) -> list[dict]:
    """Every event row CaseDesk writes, with audit lag and duplicates, in write order."""
    rows = []
    for ev in events:
        rng = rng_for(seed, "event-dq", ev["seq"])
        roll = rng.random()
        lag = timedelta(hours=rng.uniform(1, 36)) if roll < 0.02 else timedelta(0)
        row = {**ev, "event_id": f"EV{ev['seq']:09d}", "recorded_at": ev["event_ts"] + lag, "_copy": 0}
        rows.append(row)
        if roll > 0.995:
            rows.append(
                {**row, "recorded_at": row["recorded_at"] + timedelta(minutes=rng.randint(1, 10)), "_copy": 1}
            )
    # Row ids follow write order, so rows written by a given moment always get the same ids.
    rows.sort(key=lambda r: (r["recorded_at"], r["seq"], r["_copy"]))
    for n, row in enumerate(rows, start=1):
        row["event_row_id"] = n
    return rows


def _queue_for_status(case: dict, status: str) -> str:
    if status == "ESCALATED":
        return "Q-ESC"
    if status == "QC_PENDING":
        return "Q-QC"
    return case["queue_code"]


def case_row(case: dict, events: list[dict]) -> dict:
    """A case as the ``cases`` table holds it after ``events`` (its history so far, in order)."""
    last = events[-1]
    closed = next((e for e in reversed(events) if e["event_type"] == "CLOSED"), None)
    return {
        **{k: v for k, v in case.items() if not k.startswith("_")},
        "queue_code": _queue_for_status(case, last["to_status"]),
        "status": last["to_status"],
        "assignee_employee_id": last["assignee_employee_id"],
        "closed_at": closed["event_ts"] if closed else None,
        "outcome": closed["outcome"] if closed else None,
        "updated_at": last["event_ts"],
    }


def user_changes(person: dict) -> list[datetime]:
    """When a person's ``users`` row is inserted (hire) and updated (leave)."""
    joined = _at(person["hire_date"], 6)
    return [joined] + ([_at(person["leave_date"], 18)] if person["leave_date"] else [])


def user_row(person: dict, as_of: datetime) -> dict | None:
    joined, *rest = user_changes(person)
    if joined > as_of:
        return None
    inactive = bool(rest) and rest[0] <= as_of
    return {
        "employee_id": person["employee_id"],
        "display_name": f"{person['first_name']} {person['last_name']}",
        "email": person["email"],
        "is_active": not inactive,
        "created_at": joined,
        "updated_at": rest[0] if inactive else joined,
    }


def project_row(project: dict) -> dict:
    created = _at(project["start_date"] - timedelta(days=14))
    return {**project, "created_at": created, "updated_at": created}


def casedesk_tables(md: MasterData, sim: SimulationResult, rows: list[dict], as_of: datetime) -> dict:
    """Every table's rows as the database holds them at ``as_of``."""
    by_case: dict[int, list[dict]] = {}
    for ev in sim.events:
        if ev["event_ts"] <= as_of:
            by_case.setdefault(ev["case_id"], []).append(ev)
    cases = []
    for case in sim.cases:
        events = by_case.get(case["case_id"])
        if events:
            events.sort(key=lambda e: (e["event_ts"], e["seq"]))
            cases.append(case_row(case, events))
    users = [row for person in md.staff if (row := user_row(person, as_of))]
    projects = [project_row(p) for p in md.projects if project_row(p)["created_at"] <= as_of]
    return {
        **static_tables(),
        "users": users,
        "remediation_projects": projects,
        "cases": cases,
        "case_events": [r for r in rows if r["recorded_at"] <= as_of],
    }


def static_tables() -> dict[str, list[dict]]:
    """Reference tables that exist from the day CaseDesk went live."""
    return {
        "case_types": [
            {
                "case_type_code": code,
                "case_type_name": spec["name"],
                "queue_code": spec["queue"],
                "sla_days": spec["sla_days"],
                "created_at": SYSTEM_START,
                "updated_at": SYSTEM_START,
            }
            for code, spec in CASE_TYPES.items()
        ],
        "queues": [
            {
                "queue_code": code,
                "queue_name": name,
                "case_type_code": case_type,
                "created_at": SYSTEM_START,
                "updated_at": SYSTEM_START,
            }
            for code, (name, case_type) in QUEUES.items()
        ],
    }


def write_casedesk(md: MasterData, sim: SimulationResult, out_dir: Path, as_of: datetime) -> dict[str, int]:
    rows = recorded_events(md.cfg.seed, sim.events)
    counts = {}
    for table, table_rows in casedesk_tables(md, sim, rows, as_of).items():
        counts[table] = write_csv(out_dir / "casedesk" / f"{table}.csv", TABLE_COLUMNS[table], table_rows)
    return counts
