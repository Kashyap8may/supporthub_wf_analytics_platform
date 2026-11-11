"""Source 2: the activity tracker REST API (API Gateway + Lambda + DynamoDB).

Writes ``segments.jsonl``: one document per activity segment (an analyst in one state for a
stretch of time), as the API returns them at ``as_of``. A segment still running at ``as_of``
has no ``end_ts`` yet.

Data problems carried over from real desktop trackers:
- Analysts are identified by Windows network login (``SHPUN\\asharma07``), not the HR employee
  id, and some workstations report the login in upper case.
- About 1% of segments never get an end time (the tracker crashed or the PC was switched off).
- About 1% of segments overlap the next one by a few minutes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..master import MasterData
from ..rng import rng_for
from ..simulation import SimulationResult
from .common import write_jsonl


def upper_case_logins(md: MasterData) -> set[str]:
    """Employees whose workstation reports the login in upper case."""
    return {
        s["employee_id"]
        for s in md.staff
        if rng_for(md.cfg.seed, "login-case", s["employee_id"]).random() < 0.05
    }


def recorded_end(seed: int, seg: dict) -> datetime | None:
    """The end time the tracker records, with its data problems: never ended, or overlapping."""
    rng = rng_for(seed, "segment-dq", seg["segment_no"])
    roll = rng.random()
    if roll < 0.01:
        return None
    if roll < 0.02:
        return seg["end_ts"] + timedelta(minutes=rng.randint(1, 5))
    return seg["end_ts"]


def segment_document(md: MasterData, seg: dict, upper: set[str], as_of: datetime) -> dict:
    """One segment as the API returns it at ``as_of`` (no end time until it has ended)."""
    person = md.by_id[seg["employee_id"]]
    end = recorded_end(md.cfg.seed, seg)
    if end is not None and end > as_of:
        end = None
    login = person["network_login"].upper() if person["employee_id"] in upper else person["network_login"]
    return {
        "segment_id": f"SEG{seg['segment_no']:09d}",
        "login": login,
        "state": seg["state"],
        "start_ts": seg["start_ts"],
        "end_ts": end,
        "workstation": f"{person['site_code']}-WS{int(person['employee_id'][1:]) % 400:03d}",
        "updated_at": end or seg["start_ts"],
    }


def segment_documents(md: MasterData, sim: SimulationResult, as_of: datetime):
    upper = upper_case_logins(md)
    for seg in sim.activities:
        if seg["start_ts"] <= as_of:
            yield segment_document(md, seg, upper, as_of)


def write_activity_api(
    md: MasterData, sim: SimulationResult, out_dir: Path, as_of: datetime
) -> dict[str, int]:
    n = write_jsonl(out_dir / "activity_api" / "segments.jsonl", segment_documents(md, sim, as_of))
    return {"activity_segments": n}
