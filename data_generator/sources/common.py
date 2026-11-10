"""Small helpers shared by the source writers."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path


def iso(value: date | datetime) -> str:
    """ISO 8601 text; timestamps are cut to whole seconds like most source systems store them."""
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return value.isoformat()


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return iso(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def json_default(value):
    if isinstance(value, (datetime, date)):
        return iso(value)
    raise TypeError(f"not JSON serialisable: {type(value)}")


def write_csv(path: Path, columns: list[str], rows: Iterable[dict], delimiter: str = ",") -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=delimiter, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([fmt(row.get(c)) for c in columns])
            n += 1
    return n


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=json_default) + "\n")
            n += 1
    return n
