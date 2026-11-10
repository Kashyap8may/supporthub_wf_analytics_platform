"""The data contracts in contracts/ must match what the generator writes."""

import csv
import json
from pathlib import Path

import yaml

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


def _contract(name):
    return yaml.safe_load((CONTRACTS / f"{name}.yaml").read_text())


def _names(columns):
    return [c["name"] for c in columns]


def _csv_header(path):
    with path.open(encoding="utf-8") as fh:
        return next(csv.reader(fh))


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _check_values(rows, columns):
    for column in columns:
        allowed = column.get("values")
        for row in rows:
            value = row[column["name"]]
            if value in (None, ""):
                assert column.get("nullable"), (column["name"], row)
            elif allowed:
                assert value in allowed, (column["name"], value)


def test_casedesk_tables(generated):
    out, _ = generated
    for table, spec in _contract("casedesk")["tables"].items():
        path = out / "casedesk" / f"{table}.csv"
        assert _csv_header(path) == _names(spec["columns"]), table
        with path.open(encoding="utf-8", newline="") as fh:
            _check_values(list(csv.DictReader(fh)), spec["columns"])


def test_activity_api(generated):
    out, _ = generated
    spec = _contract("activity_api")
    rows = _jsonl(out / "activity_api" / "segments.jsonl")
    assert all(list(r) == _names(spec["columns"]) for r in rows)
    _check_values(rows, spec["columns"])


def test_hr_roster(generated):
    out, _ = generated
    spec = _contract("hr_roster")
    for path in (out / "s3" / "hr" / "roster").rglob("*.csv"):
        assert _csv_header(path) == _names(spec["columns"])
        with path.open(encoding="utf-8", newline="") as fh:
            _check_values(list(csv.DictReader(fh)), spec["columns"])


def test_qc_results(generated):
    out, _ = generated
    spec = _contract("qc_results")
    for path in (out / "s3" / "qc" / "results").rglob("*.jsonl"):
        rows = _jsonl(path)
        assert all(list(r) == _names(spec["columns"]) for r in rows)
        _check_values(rows, spec["columns"])


def test_wfm_exports(generated):
    out, _ = generated
    feeds = _contract("wfm_exports")["feeds"]
    for feed, folder, pattern in [
        ("forecasts", "forecasts", "FCST_*.csv"),
        ("schedules", "schedules", "SCH_*.csv"),
        ("remediation_plans", "remediation", "REMPLAN_*.csv"),
    ]:
        files = list((out / "sftp" / "wfm" / folder).glob(pattern))
        assert files, feed
        for path in files:
            assert _csv_header(path) == _names(feeds[feed]["columns"]), path.name
            with path.open(encoding="utf-8", newline="") as fh:
                _check_values(list(csv.DictReader(fh)), feeds[feed]["columns"])
