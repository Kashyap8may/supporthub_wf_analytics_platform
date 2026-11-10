import csv
import hashlib
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import timedelta

import pytest

from data_generator.config import GeneratorConfig
from data_generator.simulate import end_of, generate
from data_generator.simulation import STATUS_AFTER


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "_manifest.json"):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_same_seed_gives_identical_output(generated, small_cfg, tmp_path):
    out, _ = generated
    generate(small_cfg, tmp_path)
    assert _tree_hash(out) == _tree_hash(tmp_path)


def test_adding_a_day_never_changes_earlier_days(small_cfg, tmp_path):
    shorter, longer = tmp_path / "shorter", tmp_path / "longer"
    shorter.mkdir()
    longer.mkdir()
    as_of = end_of(small_cfg.end_date)
    generate(small_cfg, shorter, as_of)
    generate(replace(small_cfg, days=small_cfg.days + 1), longer, as_of)
    for path in (p for p in shorter.rglob("*") if p.is_file() and p.name != "_manifest.json"):
        assert (longer / path.relative_to(shorter)).read_bytes() == path.read_bytes(), path.relative_to(
            shorter
        )


def test_days_cannot_exceed_the_horizon():
    with pytest.raises(ValueError):
        GeneratorConfig(days=366, horizon_days=365)


def test_every_source_has_data(generated):
    _, manifest = generated
    for key in ["cases", "case_events", "users", "activity_segments", "roster_rows", "qc_results"]:
        assert manifest["counts"][key] > 0, key
    for key in ["forecast_files", "schedule_files", "remediation_plan_files"]:
        assert manifest["counts"][key] > 0, key


def test_case_histories_are_consistent(simulated):
    _, sim = simulated
    by_case = defaultdict(list)
    for ev in sim.events:
        by_case[ev["case_id"]].append(ev)
    for events in by_case.values():
        events.sort(key=lambda e: (e["event_ts"], e["seq"]))
        assert events[0]["event_type"] == "CREATED"
        for before, after in zip(events, events[1:], strict=False):
            assert after["from_status"] == before["to_status"], (before, after)
        for ev in events:
            assert ev["to_status"] == STATUS_AFTER[ev["event_type"]]
        closed = [e for e in events if e["event_type"] == "CLOSED"]
        assert len(closed) <= 1
        if closed:
            assert events[-1] is closed[0]


def test_people_only_work_while_logged_in_and_productive(simulated):
    """Every case a person starts falls inside one of their productive activity segments."""
    _, sim = simulated
    productive = defaultdict(list)
    for seg in sim.activities:
        if seg["state"] == "PRODUCTIVE":
            productive[seg["employee_id"]].append((seg["start_ts"], seg["end_ts"]))
    starts = [e for e in sim.events if e["event_type"] in ("ASSIGNED", "QC_STARTED", "ESCALATION_STARTED")]
    assert starts
    for ev in starts:
        windows = productive[ev["actor_employee_id"]]
        assert any(s <= ev["event_ts"] <= e for s, e in windows), ev


def test_activity_segments_do_not_overlap_before_data_problems(simulated):
    _, sim = simulated
    by_person = defaultdict(list)
    for seg in sim.activities:
        by_person[seg["employee_id"]].append(seg)
    for segs in by_person.values():
        segs.sort(key=lambda s: s["start_ts"])
        for a, b in zip(segs, segs[1:], strict=False):
            assert a["end_ts"] <= b["start_ts"]


def test_casedesk_has_late_and_duplicate_events(generated):
    out, _ = generated
    rows = _read_csv(out / "casedesk" / "case_events.csv")
    assert any(r["recorded_at"] > r["event_ts"] for r in rows)
    assert any(n > 1 for n in Counter(r["event_id"] for r in rows).values())
    assert len({r["event_row_id"] for r in rows}) == len(rows)


def test_case_rows_match_their_event_history(generated, simulated):
    out, _ = generated
    _, sim = simulated
    as_of = end_of(sim.cases[0]["created_at"].date() + timedelta(days=11))
    last = {}
    for ev in sorted(sim.events, key=lambda e: (e["event_ts"], e["seq"])):
        if ev["event_ts"] <= as_of:
            last[ev["case_id"]] = ev["to_status"]
    for row in _read_csv(out / "casedesk" / "cases.csv"):
        assert row["status"] == last[int(row["case_id"])]


def test_every_qc_result_has_a_qc_event(simulated):
    _, sim = simulated
    qc_events = sum(1 for e in sim.events if e["event_type"] in ("QC_PASSED", "QC_FAILED"))
    assert qc_events == len(sim.qc_results)
    failed = sum(1 for r in sim.qc_results if r["result"] == "FAIL")
    assert 0 < failed < len(sim.qc_results)


def test_roster_covers_everyone_in_casedesk(generated):
    out, _ = generated
    roster = set()
    for path in (out / "s3" / "hr" / "roster").rglob("roster.csv"):
        roster |= {r["employee_id"] for r in _read_csv(path)}
    actors = {r["actor_employee_id"] for r in _read_csv(out / "casedesk" / "case_events.csv")} - {""}
    assert actors <= roster


def test_schedule_republished_only_when_something_changed(generated):
    out, _ = generated
    folder = out / "sftp" / "wfm" / "schedules"
    for v2 in folder.glob("*_v2.csv"):
        v1 = v2.with_name(v2.name.replace("_v2", "_v1"))
        strip = [
            {k: v for k, v in r.items() if k not in ("schedule_version", "published_at")}
            for r in _read_csv(v1)
        ]
        assert strip != [
            {k: v for k, v in r.items() if k not in ("schedule_version", "published_at")}
            for r in _read_csv(v2)
        ]


def test_remediation_plans_cover_the_scope(generated):
    out, _ = generated
    for path in (out / "sftp" / "wfm" / "remediation").glob("*.csv"):
        rows = _read_csv(path)
        scope = int(rows[0]["scope_cases"])
        assert sum(int(r["planned_release"]) for r in rows) == scope
        assert scope - len(rows) <= sum(int(r["planned_completions"]) for r in rows) <= scope
