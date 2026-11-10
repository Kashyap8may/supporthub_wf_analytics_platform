"""Master data shared by every source: staff (with hires, leavers, team moves and booked leave),
remediation projects, and the planned schedule of each person on each day.

Everything is decided over the fixed ``horizon_days`` calendar, never over ``days``, so that a
longer run never changes what a shorter run already produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from faker import Faker

from .config import GeneratorConfig
from .reference import REMEDIATION_PROJECTS, SITES, TEAMS, is_business_day
from .rng import rng_for

NEW_HIRE_FULL_TRAINING_DAYS = 10
NEW_HIRE_HALF_TRAINING_DAYS = 10


@dataclass
class MasterData:
    cfg: GeneratorConfig
    staff: list[dict] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.by_id: dict[str, dict] = {}

    def index(self) -> None:
        self.by_id = {s["employee_id"]: s for s in self.staff}


def team_on(person: dict, day: date) -> str:
    team = person["team_id"]
    for moved_on, new_team in person["_team_moves"]:
        if moved_on <= day:
            team = new_team
    return team


def employed_on(person: dict, day: date) -> bool:
    return person["hire_date"] <= day and (person["leave_date"] is None or day < person["leave_date"])


def _login(domain: str, first: str, last: str, n: int) -> str:
    clean = "".join(ch for ch in f"{first[0]}{last}" if ch.isalpha()).lower()
    return f"{domain}\\{clean}{n:02d}"


def build_master(cfg: GeneratorConfig) -> MasterData:
    md = MasterData(cfg)
    fakers = {}
    for code, site in SITES.items():
        fakers[code] = Faker(site["locale"])
        fakers[code].seed_instance(cfg.seed + len(fakers))
    counter = iter(range(10001, 99999))

    def new_person(team_id: str, role: str, hire_date: date, rng) -> dict:
        _name, site, _role, _skills, _n = TEAMS[team_id]
        fake = fakers[site]
        first, last = fake.first_name(), fake.last_name()
        emp = f"E{next(counter)}"
        return {
            "employee_id": emp,
            "network_login": _login(SITES[site]["login_domain"], first, last, rng.randint(1, 99)),
            "first_name": first,
            "last_name": last,
            "email": f"{first}.{last}@supporthub.example".lower().replace(" ", ""),
            "site_code": site,
            "team_id": team_id,
            "role": role,
            "hire_date": hire_date,
            "leave_date": None,
            "fte": 1.0,
            # Hidden: personal speed and accuracy, team moves, booked leave.
            "_speed": rng.uniform(0.85, 1.2),
            "_error_factor": rng.uniform(0.6, 1.6),
            "_coaching_weekday": rng.randrange(5),
            "_team_moves": [],
            "_leave": {},
        }

    horizon_start, horizon_end = cfg.start_date, cfg.horizon_end
    pending = []
    for team_id, (_name, _site, role, _skills, size) in TEAMS.items():
        members = max(2 if role == "ANALYST" else 1, round(size * cfg.staff_scale))
        rng = rng_for(cfg.seed, "team", team_id)
        lead = new_person(team_id, "TEAM_LEAD", horizon_start - timedelta(days=rng.randint(700, 2500)), rng)
        lead["_lead_of"] = team_id
        md.staff.append(lead)
        for _ in range(members):
            hired = horizon_start - timedelta(days=rng.randint(60, 2200))
            pending.append(new_person(team_id, role, hired, rng))

    # Attrition with replacements: a leaver's seat is refilled a few weeks later by a new hire.
    while pending:
        person = pending.pop(0)
        md.staff.append(person)
        rng = rng_for(cfg.seed, "career", person["employee_id"])
        month = max(person["hire_date"], horizon_start)
        while month <= horizon_end:
            if rng.random() < 0.012:
                person["leave_date"] = month + timedelta(days=rng.randint(0, 27))
                break
            month += timedelta(days=28)
        if person["leave_date"] and person["leave_date"] <= horizon_end:
            refill = person["leave_date"] + timedelta(days=rng.randint(14, 35))
            if refill <= horizon_end:
                pending.append(new_person(person["team_id"], person["role"], refill, rng))
        if person["role"] == "ANALYST":
            same_site = [t for t, v in TEAMS.items() if v[1] == person["site_code"] and v[2] == "ANALYST"]
            quarter = max(person["hire_date"] + timedelta(days=120), horizon_start)
            while quarter <= horizon_end and (person["leave_date"] is None or quarter < person["leave_date"]):
                if rng.random() < 0.04:
                    current = team_on(person, quarter)
                    choices = [t for t in same_site if t != current]
                    person["_team_moves"].append(
                        (quarter + timedelta(days=rng.randint(0, 60)), rng.choice(choices))
                    )
                quarter += timedelta(days=91)
            person["_team_moves"].sort()
        _book_leave(person, cfg, rng)

    leads = {s["_lead_of"]: s["employee_id"] for s in md.staff if s.get("_lead_of")}
    for person in md.staff:
        person["_leads"] = leads
    md.staff.sort(key=lambda s: s["employee_id"])
    md.index()

    for pid, name, start, deadline, scope in REMEDIATION_PROJECTS:
        md.projects.append(
            {
                "project_id": pid,
                "project_name": name,
                "start_date": start,
                "deadline": deadline,
                "scope_cases": max(20, round(scope * cfg.staff_scale)),
            }
        )
    return md


def _book_leave(person: dict, cfg: GeneratorConfig, rng) -> None:
    """About 20 days of annual leave a year in blocks; some booked only days in advance."""
    day = max(person["hire_date"] + timedelta(days=60), cfg.start_date - timedelta(days=30))
    end = cfg.horizon_end
    while day <= end:
        day += timedelta(days=rng.randint(40, 110))
        length = rng.choice([1, 1, 2, 3, 5, 5])
        booked_on = day - timedelta(days=rng.choice([2, 4, 7, 14, 30, 45, 60]))
        taken = 0
        d = day
        while taken < length:
            if is_business_day(person["site_code"], d):
                person["_leave"][d] = booked_on
                taken += 1
            d += timedelta(days=1)
        day = d


def manager_of(person: dict, day: date) -> str | None:
    if person["role"] == "TEAM_LEAD":
        return None
    return person["_leads"].get(team_on(person, day))


def project_for_overtime(md: MasterData, team_id: str, day: date) -> bool:
    """Remediation teams work Saturday mornings in the last three weeks before a deadline."""
    if day.weekday() != 5 or "REM" not in TEAMS[team_id][3]:
        return False
    return any(p["deadline"] - timedelta(days=21) <= day <= p["deadline"] for p in md.projects)


def planned_day(
    md: MasterData, person: dict, day: date, known_on: date
) -> list[tuple[str, datetime, datetime]] | None:
    """The person's plan for ``day`` as the WFM tool knew it on ``known_on``.

    Returns segments (activity, start, end) in site-local time covering the shift, a single
    LEAVE segment, or None when the person is not rostered that day.
    """
    if not employed_on(person, day):
        return None
    site = SITES[person["site_code"]]
    tz = ZoneInfo(site["timezone"])
    team = team_on(person, day)
    overtime = project_for_overtime(md, team, day)
    if not is_business_day(person["site_code"], day) and not overtime:
        return None

    def at(t: time, plus: int = 0) -> datetime:
        return datetime.combine(day, t, tzinfo=tz) + timedelta(minutes=plus)

    start = at(site["shift_start"])
    if overtime and not is_business_day(person["site_code"], day):
        return _fill(start, start + timedelta(minutes=240), [("BREAK", *_span(start, 120, 15))])

    booked = person["_leave"].get(day)
    if booked is not None and booked <= known_on:
        return [("LEAVE", start, at(site["shift_end"]))]

    end = at(site["shift_end"])
    blocks = [("MEETING", *_span(start, 0, 15)), ("BREAK", *_span(start, 120, 15))]
    blocks.append(("LUNCH", *_span(start, 240, site["lunch_minutes"])))
    blocks.append(("BREAK", *_span(start, 390, 15)))
    if day.weekday() == 2:
        blocks.append(("MEETING", *_span(start, 180, 30)))
    if person["role"] != "TEAM_LEAD" and day.weekday() == person["_coaching_weekday"]:
        blocks.append(("COACHING", *_span(start, 300, 30)))

    worked = business_days_since_hire(person, day)
    if worked < NEW_HIRE_FULL_TRAINING_DAYS:
        training = [("TRAINING", start + timedelta(minutes=15), end)]
    elif worked < NEW_HIRE_FULL_TRAINING_DAYS + NEW_HIRE_HALF_TRAINING_DAYS:
        training = [("TRAINING", *_span(start, 15, 225))]
    else:
        rng = rng_for(md.cfg.seed, "training", person["employee_id"], day)
        training = []
        if rng.random() < 0.06:
            # Half of the ad hoc training sessions are added after the schedule was published.
            added_on = day - timedelta(days=rng.choice([1, 2, 10, 20]))
            if added_on <= known_on:
                training = [("TRAINING", *_span(start, 15, 105))]
    return _fill(start, end, training + blocks)


def _span(start: datetime, offset: int, minutes: int) -> tuple[datetime, datetime]:
    begin = start + timedelta(minutes=offset)
    return begin, begin + timedelta(minutes=minutes)


def business_days_since_hire(person: dict, day: date, cap: int = 60) -> int:
    """Business days worked before ``day``, counted up to ``cap`` (enough for ramp-up rules)."""
    if (day - person["hire_date"]).days > cap * 2:
        return cap
    d, n = person["hire_date"], 0
    while d < day and n < cap:
        n += is_business_day(person["site_code"], d)
        d += timedelta(days=1)
    return n


def fill_day(
    start: datetime, end: datetime, blocks: list[tuple[str, datetime, datetime]], filler: str = "WORK"
):
    """Lay blocks over [start, end) (earlier-listed blocks win) and fill the gaps with ``filler``."""
    return _fill(start, end, blocks, filler)


def _fill(start: datetime, end: datetime, blocks: list[tuple[str, datetime, datetime]], filler: str = "WORK"):
    """Lay non-work blocks over the shift (earlier-listed blocks win) and fill gaps with WORK."""
    placed: list[tuple[str, datetime, datetime]] = []
    for activity, b_start, b_end in blocks:
        b_start, b_end = max(b_start, start), min(b_end, end)
        for _a, p_start, p_end in placed:
            if b_start < p_end and p_start < b_end:
                # Keep only the part of the block before the clash; a clash at the start drops it.
                b_end = min(b_end, p_start) if b_start < p_start else b_start
        if b_end > b_start:
            placed.append((activity, b_start, b_end))
    placed.sort(key=lambda b: b[1])
    out, cursor = [], start
    for activity, b_start, b_end in placed:
        if b_start > cursor:
            out.append((filler, cursor, b_start))
        out.append((activity, b_start, b_end))
        cursor = max(cursor, b_end)
    if cursor < end:
        out.append((filler, cursor, end))
    return out
