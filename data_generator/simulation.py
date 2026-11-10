"""Day-by-day simulation of the KYC operation.

Each day: new cases arrive in CaseDesk; everyone rostered builds their actual day from the plan
(late logins, overrunning breaks, sick days); then the workforce is run in time order. Whoever
is free next picks the most urgent case they are skilled for, works it for a sampled handle
time across their productive time, and the case moves on: pending customer information,
escalation to a senior reviewer, QC with rework, or closure. Every move is a case event.

Nothing here reads ``cfg.days``: a day's results depend only on that day and earlier ones.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from .config import GeneratorConfig
from .master import (
    MasterData,
    business_days_since_hire,
    employed_on,
    fill_day,
    manager_of,
    planned_day,
    team_on,
)
from .reference import CASE_TYPES, HOLIDAYS, OUTCOMES, QC_ERROR_CATEGORIES, REMEDIATION_TRANCHES, SITES, TEAMS
from .rng import lognormal_minutes, poisson_like, rng_for

STATUS_AFTER = {
    "CREATED": "NEW",
    "ASSIGNED": "ASSIGNED",
    "STARTED": "IN_PROGRESS",
    "PENDED": "PENDING_CUSTOMER",
    "CUSTOMER_RESPONDED": "ASSIGNED",
    "ESCALATED": "ESCALATED",
    "ESCALATION_STARTED": "ESCALATED",
    "ESCALATION_RESOLVED": "ASSIGNED",
    "SUBMITTED_FOR_QC": "QC_PENDING",
    "QC_STARTED": "QC_PENDING",
    "QC_PASSED": "QC_PASSED",
    "QC_FAILED": "REWORK",
    "RETURNED_TO_QUEUE": "NEW",
    "REASSIGNED": "NEW",
    "CLOSED": "CLOSED",
}

WORKING_ROLES = {"ANALYST", "SENIOR_REVIEWER", "QC_CHECKER"}
NO_RESPONSE_CLOSE = timedelta(days=14)
ONB_WEEKDAY_FACTOR = [1.2, 1.05, 1.0, 1.0, 0.9, 0.12, 0.06]


@dataclass
class SimulationResult:
    cases: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    activities: list[dict] = field(default_factory=list)
    qc_results: list[dict] = field(default_factory=list)


@dataclass
class WorkerDay:
    person: dict
    day: date
    skills: list[str]
    windows: list[tuple[datetime, datetime]]

    def align(self, t: datetime) -> datetime | None:
        """``t`` if it falls in productive time, else the start of the next productive window."""
        for start, end in self.windows:
            if t < end:
                return max(t, start)
        return None

    def advance(self, t: datetime, minutes: float) -> tuple[datetime, float, bool]:
        """Spend up to ``minutes`` of productive time from ``t``: (end, minutes used, finished)."""
        left = minutes
        cursor = t
        for start, end in self.windows:
            if cursor >= end:
                continue
            cursor = max(cursor, start)
            room = (end - cursor).total_seconds() / 60
            if room >= left:
                return cursor + timedelta(minutes=left), minutes, True
            left -= room
            cursor = end
        return cursor, minutes - left, False


# ---------------------------------------------------------------------- arrivals (shared with WFM)


def first_business_day_of_month(day: date) -> bool:
    d = day.replace(day=1)
    while d.weekday() >= 5 or any(d in HOLIDAYS[s] for s in SITES):
        d += timedelta(days=1)
    return d == day


def remediation_tranches(project: dict) -> list[tuple[date, int]]:
    """When each part of a remediation book is loaded into CaseDesk, and how many cases."""
    out, loaded = [], 0
    for n, (weeks, share) in enumerate(REMEDIATION_TRANCHES):
        last = n == len(REMEDIATION_TRANCHES) - 1
        size = project["scope_cases"] - loaded if last else round(project["scope_cases"] * share)
        out.append((project["start_date"] + timedelta(weeks=weeks), size))
        loaded += size
    return out


def remediation_batch(project: dict, day: date) -> int:
    return sum(size for loaded_on, size in remediation_tranches(project) if loaded_on == day)


def expected_arrivals(cfg: GeneratorConfig, md: MasterData, case_type: str, day: date) -> float:
    """The mean number of new cases of a type on a day, before random variation."""
    if case_type == "ONB":
        month_end = (day + timedelta(days=3)).month != day.month and day.weekday() < 5
        return cfg.onboarding_per_day * ONB_WEEKDAY_FACTOR[day.weekday()] * (1.15 if month_end else 1.0)
    if case_type == "EDD":
        return cfg.edd_per_day * (1.0 if day.weekday() < 5 else 0.3)
    if case_type == "PRD":
        return cfg.periodic_per_month if first_business_day_of_month(day) else 0
    return sum(remediation_batch(p, day) for p in md.projects)


def _utc(day: date, hour: float) -> datetime:
    return datetime.combine(day, time(0), tzinfo=UTC) + timedelta(hours=hour)


# ---------------------------------------------------------------------- simulation


class Simulation:
    def __init__(self, cfg: GeneratorConfig, md: MasterData):
        self.cfg = cfg
        self.md = md
        self.out = SimulationResult()
        self.cases: dict[int, dict] = {}
        self.case_ids = itertools.count(1)
        self.event_seq = itertools.count(1)
        self.tie = itertools.count()
        self.qc_ids = itertools.count(1)
        self.activity_seq = itertools.count(1)
        # (available_at, tie, case_id, target) where target is a queue code or ("person", id).
        self.future: list = []
        self.queues: dict[str, list] = {q: [] for q in ["Q-ONB", "Q-PRD", "Q-EDD", "Q-REM", "Q-ESC", "Q-QC"]}
        self.personal: dict[str, list] = {}

    def run(self) -> SimulationResult:
        for day in self.cfg.dates():
            self._day(day)
        return self.out

    # ------------------------------------------------------------------ one day
    def _day(self, day: date) -> None:
        self._arrivals(day)
        self._release(_utc(day, 0))
        present: dict[str, WorkerDay | None] = {}
        for person in self.md.staff:
            plan = planned_day(self.md, person, day, known_on=day)
            if plan is None or plan[0][0] == "LEAVE":
                continue
            rng = rng_for(self.cfg.seed, "attendance", person["employee_id"], day)
            if rng.random() < 0.03:
                continue  # unplanned absence: rostered, never logs in
            segments = self._actual_day(person, plan, rng)
            for state, start, end in segments:
                self.out.activities.append(
                    {
                        "segment_no": next(self.activity_seq),
                        "employee_id": person["employee_id"],
                        "state": state,
                        "start_ts": start,
                        "end_ts": end,
                    }
                )
            if person["role"] in WORKING_ROLES:
                windows = [(s, e) for state, s, e in segments if state == "PRODUCTIVE"]
                present[person["employee_id"]] = WorkerDay(person, day, self._skills(person, day), windows)
            else:
                present[person["employee_id"]] = None
        self._reassign_absent(day, present)

        heap = []
        for emp, wd in present.items():
            if wd and wd.windows:
                heapq.heappush(heap, (wd.windows[0][0], next(self.tie), emp))
        while heap:
            t, _, emp = heapq.heappop(heap)
            nxt = self._step(present[emp], t)
            if nxt is not None:
                heapq.heappush(heap, (nxt, next(self.tie), emp))

    def _skills(self, person: dict, day: date) -> list[str]:
        if person["role"] == "SENIOR_REVIEWER":
            return ["Q-ESC"]
        if person["role"] == "QC_CHECKER":
            return ["Q-QC"]
        return [CASE_TYPES[ct]["queue"] for ct in TEAMS[team_on(person, day)][3]]

    def _actual_day(self, person: dict, plan, rng) -> list[tuple[str, datetime, datetime]]:
        """What the activity tracker sees: the plan with late logins, overruns and early logouts."""
        lead = person["role"] == "TEAM_LEAD"
        login = plan[0][1] + timedelta(minutes=min(max(rng.gauss(2, 6), -10), 30))
        logout = plan[-1][2] + timedelta(minutes=min(max(rng.gauss(-2, 8), -45), 20))
        blocks = []
        for activity, start, end in plan:
            if activity == "WORK":
                continue
            if activity in ("BREAK", "LUNCH"):
                over = min(max(rng.gauss(1, 3), 0), 15)
            else:
                over = min(max(rng.gauss(0, 3), 0), 10)
            blocks.append((activity, start, end + timedelta(minutes=over)))
        if rng.random() < 0.3:
            after = plan[0][2] if plan[0][0] == "MEETING" else login
            blocks.append(("ADMIN", after, after + timedelta(minutes=rng.randint(10, 20))))
        filler = "ADMIN" if lead else "PRODUCTIVE"
        segments = fill_day(login, logout, blocks, filler=filler)
        # The tracker records whole seconds, like the case events.
        out = []
        for state, start, end in segments:
            start, end = (
                start.astimezone(UTC).replace(microsecond=0),
                end.astimezone(UTC).replace(microsecond=0),
            )
            if end > start:
                out.append((state, start, end))
        return out

    # ------------------------------------------------------------------ arrivals
    def _arrivals(self, day: date) -> None:
        new = []
        for case_type in ["ONB", "EDD", "PRD", "REM"]:
            rng = rng_for(self.cfg.seed, "arrivals", case_type, day)
            if case_type == "REM":
                for project in self.md.projects:
                    for i in range(remediation_batch(project, day)):
                        new.append((_utc(day, 5) + timedelta(seconds=i), case_type, project, rng))
                continue
            mean = expected_arrivals(self.cfg, self.md, case_type, day)
            if case_type == "PRD":
                for i in range(int(mean)):
                    new.append((_utc(day, 6) + timedelta(seconds=i), case_type, None, rng))
                continue
            for _ in range(poisson_like(rng, mean)):
                hour = rng.uniform(3, 19) if case_type == "ONB" else rng.uniform(0, 24)
                new.append((_utc(day, hour), case_type, None, rng))
        new.sort(key=lambda n: (n[0], n[1]))
        for created_at, case_type, project, _rng in new:
            self._create(created_at, case_type, project)

    def _create(self, created_at: datetime, case_type: str, project: dict | None) -> None:
        case_id = next(self.case_ids)
        rng = rng_for(self.cfg.seed, "case", case_id)
        spec = CASE_TYPES[case_type]
        if case_type == "EDD":
            risk = rng.choices(["HIGH", "MEDIUM"], [0.6, 0.4])[0]
        elif case_type == "PRD":
            risk = rng.choices(["HIGH", "MEDIUM", "LOW"], [0.2, 0.35, 0.45])[0]
        else:
            risk = rng.choices(["HIGH", "MEDIUM", "LOW"], [0.15, 0.35, 0.5])[0]
        if case_type == "PRD":
            due = _utc(created_at.date() + timedelta(days=rng.randint(35, 75)), 23.99)
        elif case_type == "REM":
            due = _utc(project["deadline"], 23.99)
        else:
            due = created_at + timedelta(days=spec["sla_days"])
        case = {
            "case_id": case_id,
            "case_ref": f"KYC-{created_at.year}-{case_id:07d}",
            "case_type_code": case_type,
            "queue_code": spec["queue"],
            "remediation_project_id": project["project_id"] if project else None,
            "customer_ref": f"CU{rng.randint(10_000_000, 99_999_999)}",
            "customer_segment": rng.choices(["RETAIL", "BUSINESS"], [0.75, 0.25])[0],
            "risk_tier": risk,
            "priority": "HIGH" if case_type == "EDD" or risk == "HIGH" else "NORMAL",
            "created_at": created_at,
            "due_at": due.replace(microsecond=0),
            # Hidden working state.
            "_rng": rng,
            "_status": None,
            "_assignee": None,
            "_owner": None,
            "_stage": "FIRST",
            "_remaining": None,
            "_touched": False,
            "_qc_required": rng.random() < spec["qc_rate"],
            "_reworked": False,
            "_qc_attempts": 0,
        }
        self.cases[case_id] = case
        self.out.cases.append(case)
        self._event(case, "CREATED", created_at, actor=None, assignee=None)
        self._schedule(case, created_at, spec["queue"])

    # ------------------------------------------------------------------ queues
    def _schedule(self, case: dict, at: datetime, target) -> None:
        heapq.heappush(self.future, (at, next(self.tie), case["case_id"], target))

    def _release(self, now: datetime) -> None:
        while self.future and self.future[0][0] <= now:
            at, _, case_id, target = heapq.heappop(self.future)
            case = self.cases[case_id]
            if isinstance(target, tuple):
                emp = target[1]
                if not employed_on(self.md.by_id[emp], at.date()):
                    self._to_queue(case, at, reason_actor=manager_of(self.md.by_id[emp], at.date()))
                    continue
                heapq.heappush(self.personal.setdefault(emp, []), (at, next(self.tie), case_id))
            else:
                self._enqueue(case, target)

    def _enqueue(self, case: dict, queue: str) -> None:
        rank = 0 if case["priority"] == "HIGH" else 1
        heapq.heappush(self.queues[queue], (rank, case["due_at"], case["case_id"]))

    def _queue_for(self, case: dict) -> str:
        if case["_stage"] == "QC":
            return "Q-QC"
        if case["_stage"] == "ESC":
            return "Q-ESC"
        return case["queue_code"]

    def _to_queue(self, case: dict, at: datetime, reason_actor: str | None) -> None:
        """A team lead hands a case back to the queue because its owner is away or has left."""
        self._event(case, "REASSIGNED", at, actor=reason_actor, assignee=None)
        self._enqueue(case, self._queue_for(case))

    def _reassign_absent(self, day: date, present: dict) -> None:
        for emp, items in self.personal.items():
            if emp in present or not items:
                continue
            person = self.md.by_id[emp]
            at = _utc(day, 3)
            while items:
                _, _, case_id = heapq.heappop(items)
                self._to_queue(self.cases[case_id], at, reason_actor=manager_of(person, day))

    def _pick(self, wd: WorkerDay) -> dict | None:
        mine = self.personal.get(wd.person["employee_id"])
        if mine:
            return self.cases[heapq.heappop(mine)[2]]
        for queue in wd.skills:
            if self.queues[queue]:
                return self.cases[heapq.heappop(self.queues[queue])[2]]
        return None

    # ------------------------------------------------------------------ work
    def _step(self, wd: WorkerDay, t: datetime) -> datetime | None:
        self._release(t)
        t = wd.align(t)
        if t is None:
            return None
        case = self._pick(wd)
        if case is None:
            nxt = t + timedelta(minutes=15)
            if self.future and self.future[0][0] < nxt:
                nxt = max(self.future[0][0], t + timedelta(minutes=1))
            return nxt
        return self._work(wd, t, case)

    def _work(self, wd: WorkerDay, t: datetime, case: dict) -> datetime | None:
        emp = wd.person["employee_id"]
        rng = case["_rng"]
        stage = case["_stage"]
        if stage == "QC":
            if case["_assignee"] != emp:
                self._event(case, "QC_STARTED", t, actor=emp, assignee=emp)
        elif stage == "ESC":
            if case["_assignee"] != emp:
                self._event(case, "ESCALATION_STARTED", t, actor=emp, assignee=emp)
        else:
            if case["_assignee"] != emp:
                self._event(case, "ASSIGNED", t, actor=emp, assignee=emp)
                case["_owner"] = emp
            if stage == "FIRST" and not case["_touched"] and rng.random() < 0.02:
                back = t + timedelta(minutes=rng.randint(4, 12))
                self._event(case, "RETURNED_TO_QUEUE", back, actor=emp, assignee=None)
                self._schedule(case, back, case["queue_code"])
                return back
            if case["_status"] != "IN_PROGRESS":
                self._event(case, "STARTED", t + timedelta(minutes=1), actor=emp, assignee=emp)
        if case["_remaining"] is None:
            case["_remaining"] = self._handle_minutes(case, wd)
        end, used, finished = wd.advance(t, case["_remaining"])
        case["_remaining"] -= used
        if not finished:
            # Carried over: the same person continues on their next working day.
            self._schedule(case, _utc(wd.day + timedelta(days=1), 0), ("person", emp))
            return None
        case["_remaining"] = None
        self._complete(case, emp, end)
        return end

    def _handle_minutes(self, case: dict, wd: WorkerDay) -> float:
        aht = CASE_TYPES[case["case_type_code"]]["aht"]
        base = {
            "FIRST": aht,
            "RESUME": 0.3 * aht,
            "FINAL": 0.25 * aht,
            "REWORK": 0.3 * aht,
            "ESC": 45,
            "QC": max(10, 0.25 * aht),
        }[case["_stage"]]
        worked = business_days_since_hire(wd.person, wd.day)
        ramp = 1 + 0.6 * max(0, 40 - worked) / 40
        return max(3.0, lognormal_minutes(case["_rng"], base) * wd.person["_speed"] * ramp)

    def _complete(self, case: dict, emp: str, t: datetime) -> None:
        rng = case["_rng"]
        spec = CASE_TYPES[case["case_type_code"]]
        stage = case["_stage"]
        if stage in ("FIRST", "RESUME"):
            first = stage == "FIRST"
            case["_touched"] = True
            if first and rng.random() < spec["pend_rate"]:
                self._pend(case, emp, t)
            elif rng.random() < spec["escalation_rate"] * (1 if first else 0.5):
                self._event(case, "ESCALATED", t, actor=emp, assignee=None)
                case["_stage"] = "ESC"
                self._schedule(case, t, "Q-ESC")
            else:
                self._finalise(case, emp, t)
        elif stage == "FINAL":
            self._finalise(case, emp, t)
        elif stage == "REWORK":
            self._submit_qc(case, t, emp)
        elif stage == "ESC":
            owner = case["_owner"]
            self._event(case, "ESCALATION_RESOLVED", t, actor=emp, assignee=owner)
            case["_stage"] = "FINAL"
            self._schedule(case, t, ("person", owner))
        elif stage == "QC":
            self._qc(case, emp, t)

    def _pend(self, case: dict, emp: str, t: datetime) -> None:
        rng = case["_rng"]
        self._event(case, "PENDED", t, actor=emp, assignee=emp)
        wait = timedelta(hours=2 + rng.expovariate(1 / 72))
        if wait > NO_RESPONSE_CLOSE:
            self._event(
                case, "CLOSED", t + NO_RESPONSE_CLOSE, actor=None, assignee=None, outcome="EXIT_RELATIONSHIP"
            )
            return
        self._event(case, "CUSTOMER_RESPONDED", t + wait, actor=None, assignee=emp)
        case["_stage"] = "RESUME"
        self._schedule(case, t + wait, ("person", emp))

    def _finalise(self, case: dict, emp: str, t: datetime) -> None:
        if case["_qc_required"] or case["_reworked"]:
            self._submit_qc(case, t, emp)
        else:
            outcome = case["_rng"].choices([o for o, _ in OUTCOMES], [w for _, w in OUTCOMES])[0]
            self._event(case, "CLOSED", t + timedelta(minutes=1), actor=emp, assignee=emp, outcome=outcome)

    def _submit_qc(self, case: dict, t: datetime, emp: str) -> None:
        self._event(case, "SUBMITTED_FOR_QC", t, actor=emp, assignee=None)
        case["_stage"] = "QC"
        self._schedule(case, t, "Q-QC")

    def _qc(self, case: dict, checker: str, t: datetime) -> None:
        rng = case["_rng"]
        owner = self.md.by_id[case["_owner"]]
        case["_qc_attempts"] += 1
        new_hire = business_days_since_hire(owner, t.date()) < 40
        fail_p = min(0.5, 0.07 * owner["_error_factor"] * (2 if new_hire else 1))
        if case["_qc_attempts"] > 1:
            fail_p /= 3
        failed = rng.random() < fail_p
        self.out.qc_results.append(
            {
                "qc_id": next(self.qc_ids),
                "case_ref": case["case_ref"],
                "case_type_code": case["case_type_code"],
                "qc_attempt": case["_qc_attempts"],
                "checker_employee_id": checker,
                "analyst_employee_id": owner["employee_id"],
                "checked_at": t,
                "result": "FAIL" if failed else "PASS",
                "error_category": rng.choice(QC_ERROR_CATEGORIES) if failed else None,
                "error_severity": rng.choices(["MINOR", "MAJOR"], [0.7, 0.3])[0] if failed else None,
            }
        )
        if failed:
            self._event(case, "QC_FAILED", t, actor=checker, assignee=owner["employee_id"])
            case["_stage"] = "REWORK"
            case["_reworked"] = True
            self._schedule(case, t, ("person", owner["employee_id"]))
        else:
            self._event(case, "QC_PASSED", t, actor=checker, assignee=checker)
            outcome = rng.choices([o for o, _ in OUTCOMES], [w for _, w in OUTCOMES])[0]
            self._event(
                case, "CLOSED", t + timedelta(minutes=1), actor=checker, assignee=checker, outcome=outcome
            )

    def _event(
        self, case: dict, event_type: str, ts: datetime, actor: str | None, assignee: str | None, outcome=None
    ) -> None:
        to_status = STATUS_AFTER[event_type]
        self.out.events.append(
            {
                "seq": next(self.event_seq),
                "case_id": case["case_id"],
                "event_type": event_type,
                "from_status": case["_status"],
                "to_status": to_status,
                "assignee_employee_id": assignee,
                "actor_employee_id": actor,
                "outcome": outcome,
                "event_ts": ts.replace(microsecond=0),
            }
        )
        case["_status"] = to_status
        case["_assignee"] = assignee


def simulate(cfg: GeneratorConfig, md: MasterData) -> SimulationResult:
    return Simulation(cfg, md).run()
