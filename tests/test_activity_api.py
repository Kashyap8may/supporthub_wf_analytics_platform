import importlib.util
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "activity_api_handler", Path(__file__).parents[1] / "services" / "activity_api" / "handler.py"
)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)

NOW = datetime(2026, 7, 10, 12, tzinfo=UTC)


class FakeTable:
    """Just enough of a DynamoDB Table: paged query on the GSI and paged scan."""

    def __init__(self, items):
        self.items = items

    def query(self, KeyConditionExpression, ExpressionAttributeValues, Limit, ExclusiveStartKey=None, **_):
        assert KeyConditionExpression == "updated_day = :day AND updated_at > :since"
        day, since = ExpressionAttributeValues[":day"], ExpressionAttributeValues[":since"]
        matches = sorted(
            (i for i in self.items if i["updated_day"] == day and i["updated_at"] > since),
            key=lambda i: (i["updated_at"], i["segment_id"]),
        )
        return self._page(matches, Limit, ExclusiveStartKey)

    def scan(self, Limit, ExclusiveStartKey=None):
        return self._page(sorted(self.items, key=lambda i: i["segment_id"]), Limit, ExclusiveStartKey)

    @staticmethod
    def _page(rows, limit, start_key):
        start = start_key["pos"] if start_key else 0
        page = rows[start : start + limit]
        response = {"Items": page}
        if start + limit < len(rows):
            response["LastEvaluatedKey"] = {"pos": start + limit}
        return response


def _segment(n, ts):
    return {
        "segment_id": f"SEG{n:09d}",
        "updated_at": ts.isoformat(),
        "updated_day": ts.date().isoformat(),
        "minutes": Decimal("1.5"),
    }


@pytest.fixture
def table():
    start = datetime(2026, 7, 1, tzinfo=UTC)
    return FakeTable([_segment(n, start + timedelta(hours=7 * n)) for n in range(30)])


def _call(table, **params):
    response = api.handler({"queryStringParameters": params}, None, table=table, now=NOW)
    return response["statusCode"], json.loads(response["body"])


def _pull_all(table, **params):
    seen, token = [], None
    while True:
        status, body = _call(table, **params, **({"page_token": token} if token else {}))
        assert status == 200
        seen += body["activities"]
        token = body["next_page_token"]
        if not token:
            return seen


def test_incremental_pull_returns_only_newer_segments_across_pages(table):
    since = datetime(2026, 7, 3, 5, tzinfo=UTC)
    rows = _pull_all(table, updated_since=since.isoformat(), limit="4")
    expected = {i["segment_id"] for i in table.items if i["updated_at"] > since.isoformat()}
    assert [r["segment_id"] for r in rows] == sorted(expected)
    assert all("updated_day" not in r for r in rows)


def test_full_load_without_updated_since_pages_through_everything(table):
    rows = _pull_all(table, limit="7")
    assert len(rows) == len(table.items) == len({r["segment_id"] for r in rows})


def test_numbers_come_back_as_json_numbers(table):
    _, body = _call(table, limit="1")
    assert body["activities"][0]["minutes"] == 1.5


@pytest.mark.parametrize(
    "params",
    [
        {"updated_since": "yesterday"},
        {"updated_since": "2020-01-01T00:00:00Z"},
        {"limit": "0"},
        {"page_token": "not-a-token"},
    ],
)
def test_bad_requests_are_rejected(table, params):
    status, body = _call(table, **params)
    assert status == 400
    assert body["error"]
