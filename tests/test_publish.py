from datetime import date

import pytest

from data_generator.publish import batches, target_for, upsert_sql

DAY = date(2026, 7, 2)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("days/2026-07-02/casedesk/cases.csv", ("casedesk", "cases")),
        ("days/2026-07-02/activity_api/segments.jsonl", ("segments", "")),
        (
            "days/2026-07-02/s3/hr/roster/extract_date=2026-07-02/roster.csv",
            ("s3", "hr/roster/extract_date=2026-07-02/roster.csv"),
        ),
        ("days/2026-07-02/sftp/wfm/forecasts/FCST_20260706.csv", ("sftp", "wfm/forecasts/FCST_20260706.csv")),
    ],
)
def test_objects_map_to_their_source(key, expected):
    assert target_for(key, DAY) == expected


def test_unknown_objects_are_rejected():
    with pytest.raises(ValueError):
        target_for("days/2026-07-02/elsewhere/x.csv", DAY)


def test_upsert_updates_every_column_but_the_key():
    sql = upsert_sql("users", ["employee_id", "is_active", "updated_at"], "staging_users")
    assert sql.startswith("INSERT INTO casedesk.users")
    assert "ON CONFLICT (employee_id)" in sql
    assert "is_active = EXCLUDED.is_active, updated_at = EXCLUDED.updated_at" in sql
    assert "employee_id = EXCLUDED" not in sql


def test_batches_keep_order_and_cover_every_day():
    days = list(range(70))
    assert [len(b) for b in batches(days, 31)] == [31, 31, 8]
    assert sum(batches(days, 31), []) == days
