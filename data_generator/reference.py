"""Fixed reference data: sites and their calendars, case types, queues, teams, activity states.

Everything here is fictional. Holiday lists are a made-up company calendar loosely based on
public holidays in each country; they only need to differ between the sites.
"""

from __future__ import annotations

from datetime import date, time

SITES = {
    "PUN": {
        "name": "Pune",
        "country": "IN",
        "timezone": "Asia/Kolkata",
        "shift_start": time(9, 30),
        "shift_end": time(18, 30),
        "lunch_minutes": 45,
        "locale": "en_IN",
        "login_domain": "SHPUN",
    },
    "GLA": {
        "name": "Glasgow",
        "country": "GB",
        "timezone": "Europe/London",
        "shift_start": time(9, 0),
        "shift_end": time(17, 30),
        "lunch_minutes": 30,
        "locale": "en_GB",
        "login_domain": "SHGLA",
    },
}

HOLIDAYS = {
    "PUN": {
        date(2026, 8, 14),
        date(2026, 8, 28),
        date(2026, 9, 14),
        date(2026, 10, 2),
        date(2026, 10, 20),
        date(2026, 11, 9),
        date(2026, 11, 10),
        date(2026, 12, 25),
        date(2027, 1, 1),
        date(2027, 1, 26),
        date(2027, 3, 22),
        date(2027, 4, 14),
        date(2027, 5, 1),
    },
    "GLA": {
        date(2026, 8, 3),
        date(2026, 11, 30),
        date(2026, 12, 25),
        date(2026, 12, 28),
        date(2027, 1, 1),
        date(2027, 1, 4),
        date(2027, 3, 26),
        date(2027, 5, 3),
        date(2027, 5, 31),
    },
}


def is_business_day(site: str, day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS[site]


# code: name, queue, naive SLA in calendar days (what CaseDesk stamps as due_at; None = set per case),
# mean handle minutes, pending-customer rate, escalation rate, QC sample rate.
CASE_TYPES = {
    "ONB": {
        "name": "Onboarding (CDD)",
        "queue": "Q-ONB",
        "sla_days": 2,
        "aht": 35,
        "pend_rate": 0.25,
        "escalation_rate": 0.03,
        "qc_rate": 0.25,
    },
    "PRD": {
        "name": "Periodic refresh",
        "queue": "Q-PRD",
        "sla_days": None,
        "aht": 60,
        "pend_rate": 0.35,
        "escalation_rate": 0.05,
        "qc_rate": 0.20,
    },
    "EDD": {
        "name": "Event-driven review (EDD)",
        "queue": "Q-EDD",
        "sla_days": 5,
        "aht": 150,
        "pend_rate": 0.30,
        "escalation_rate": 0.25,
        "qc_rate": 1.0,
    },
    "REM": {
        "name": "Remediation",
        "queue": "Q-REM",
        "sla_days": None,
        "aht": 90,
        "pend_rate": 0.15,
        "escalation_rate": 0.04,
        "qc_rate": 0.15,
    },
}

QUEUES = {
    "Q-ONB": ("Onboarding", "ONB"),
    "Q-PRD": ("Periodic refresh", "PRD"),
    "Q-EDD": ("Event-driven reviews", "EDD"),
    "Q-REM": ("Remediation", "REM"),
    "Q-ESC": ("Escalations (senior review)", None),
    "Q-QC": ("Quality check", None),
}

# Periodic refresh cycle by customer risk tier, in years.
REFRESH_YEARS = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}

# team id: name, site, role of its members, skills in order of preference, members.
TEAMS = {
    "T01": ("Onboarding Pune A", "PUN", "ANALYST", ["ONB", "PRD"], 12),
    "T02": ("Onboarding Pune B", "PUN", "ANALYST", ["ONB", "PRD"], 12),
    "T03": ("Periodic Refresh Pune", "PUN", "ANALYST", ["PRD", "ONB"], 12),
    "T04": ("Enhanced Due Diligence Pune", "PUN", "ANALYST", ["EDD", "PRD"], 12),
    "T05": ("Refresh and Remediation Pune", "PUN", "ANALYST", ["PRD", "REM"], 12),
    "T06": ("Onboarding Glasgow", "GLA", "ANALYST", ["ONB", "EDD"], 12),
    "T07": ("Enhanced Due Diligence Glasgow", "GLA", "ANALYST", ["EDD", "ONB"], 12),
    "T08": ("Remediation Glasgow", "GLA", "ANALYST", ["REM", "PRD"], 12),
    "T09": ("Senior Review Pune", "PUN", "SENIOR_REVIEWER", ["ESC"], 4),
    "T10": ("Senior Review Glasgow", "GLA", "SENIOR_REVIEWER", ["ESC"], 6),
    "T11": ("Quality Check Pune", "PUN", "QC_CHECKER", ["QC"], 6),
    "T12": ("Quality Check Glasgow", "GLA", "QC_CHECKER", ["QC"], 4),
}

ACTIVITY_STATES = ["PRODUCTIVE", "ADMIN", "MEETING", "TRAINING", "COACHING", "BREAK", "LUNCH"]

# Planned (WFM) segment types; LEAVE marks a whole day off.
SCHEDULE_ACTIVITIES = ["WORK", "MEETING", "TRAINING", "COACHING", "BREAK", "LUNCH", "LEAVE"]

OUTCOMES = [("APPROVED", 0.88), ("REJECTED", 0.05), ("EXIT_RELATIONSHIP", 0.07)]

QC_ERROR_CATEGORIES = [
    "ID_VERIFICATION",
    "BENEFICIAL_OWNERSHIP",
    "SOURCE_OF_FUNDS",
    "SCREENING_DISPOSITION",
    "RISK_RATING",
    "DOCUMENTATION",
]

REMEDIATION_PROJECTS = [
    # id, name, start (a Monday), deadline, scope (cases)
    ("REM-01", "Beneficial ownership refresh", date(2026, 7, 6), date(2026, 10, 30), 4500),
    ("REM-02", "Address verification backfill", date(2026, 9, 7), date(2027, 1, 29), 5000),
    ("REM-03", "Legacy risk rating review", date(2027, 2, 1), date(2027, 5, 28), 4000),
]

# A remediation book is loaded in tranches: (weeks after the start, share of the scope).
REMEDIATION_TRANCHES = [(0, 0.5), (4, 0.25), (8, 0.25)]
