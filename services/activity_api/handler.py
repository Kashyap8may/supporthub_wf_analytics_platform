"""Activity tracker API: GET /activities?updated_since=<ISO timestamp>&page_token=<token>&limit=<n>.

Lambda proxy handler behind API Gateway. Activity segments live in DynamoDB with two extra attributes
the loader adds: ``updated_day`` (UTC date of ``updated_at``) and ``updated_at`` in UTC ISO form.
A GSI on (updated_day, updated_at) serves incremental pulls one day at a time, so a daily pull
never scans the whole table. Without ``updated_since`` the API pages through every segment,
which is how a first full load starts.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

DEFAULT_LIMIT = 500
MAX_LIMIT = 1000
# Bounds the number of day queries one request can make; older pulls should do a full load.
MAX_LOOKBACK_DAYS = 400
HIDDEN_ATTRIBUTES = {"updated_day"}


def handler(event, context, table=None, now: datetime | None = None):
    params = event.get("queryStringParameters") or {}
    now = now or datetime.now(UTC)
    try:
        limit = int(params.get("limit", DEFAULT_LIMIT))
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        since = _parse_since(params.get("updated_since"), now)
        state = _decode_token(params.get("page_token"))
    except ValueError as exc:
        return _response(400, {"error": str(exc)})

    table = table or _table()
    if since is None:
        items, next_state = _scan_page(table, limit, state)
    else:
        items, next_state = _incremental_page(table, since, now.date(), limit, state)
    return _response(
        200,
        {
            "activities": [{k: v for k, v in item.items() if k not in HIDDEN_ATTRIBUTES} for item in items],
            "next_page_token": _encode_token(next_state) if next_state else None,
        },
    )


def _table():
    import boto3  # available in the Lambda runtime; imported here so tests do not need it

    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _parse_since(value: str | None, now: datetime) -> datetime | None:
    if not value:
        return None
    try:
        since = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("updated_since must be an ISO 8601 timestamp") from None
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    since = since.astimezone(UTC)
    if since < now - timedelta(days=MAX_LOOKBACK_DAYS):
        raise ValueError(f"updated_since is more than {MAX_LOOKBACK_DAYS} days ago; omit it for a full load")
    return since


def _incremental_page(table, since: datetime, today: date, limit: int, state: dict | None):
    since_text = since.isoformat()
    day = date.fromisoformat(state["day"]) if state else since.date()
    start_key = state.get("start_key") if state else None
    items: list[dict] = []
    while day <= today:
        kwargs = {
            "IndexName": os.environ.get("INDEX_NAME", "by_updated_day"),
            "KeyConditionExpression": "updated_day = :day AND updated_at > :since",
            "ExpressionAttributeValues": {":day": day.isoformat(), ":since": since_text},
            "Limit": limit - len(items),
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        response = table.query(**kwargs)
        items.extend(response["Items"])
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            day += timedelta(days=1)
        if len(items) >= limit:
            if start_key:
                return items, {"day": day.isoformat(), "start_key": start_key}
            return items, ({"day": day.isoformat()} if day <= today else None)
    return items, None


def _scan_page(table, limit: int, state: dict | None):
    kwargs = {"Limit": limit}
    if state and state.get("start_key"):
        kwargs["ExclusiveStartKey"] = state["start_key"]
    response = table.scan(**kwargs)
    start_key = response.get("LastEvaluatedKey")
    return response["Items"], ({"start_key": start_key} if start_key else None)


def _encode_token(state: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(state, default=_json_default).encode()).decode()


def _decode_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        state = json.loads(base64.urlsafe_b64decode(token.encode()))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("page_token is not valid") from None
    if not isinstance(state, dict):
        raise ValueError("page_token is not valid")
    return state


def _json_default(value):
    # DynamoDB returns every number as Decimal.
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"cannot serialise {type(value).__name__}")


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }
