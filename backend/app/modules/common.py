"""Helpers shared by the report modules' routers."""
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import HTTPException

def d_str(v):
    return v.strftime("%Y-%m-%d") if isinstance(v, datetime) else v


def parse_day(s: str | None, end: bool = False) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, f"Invalid date '{s}' (expected YYYY-MM-DD)")
    return d + timedelta(days=1) - timedelta(microseconds=1) if end else d


def latest_first(rows: list[dict], key) -> list[dict]:
    """Reports are cumulative: keep, for each logical key, the row from the most recent report."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["reportDate"], str(r["_id"])), reverse=True):
        k = key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def xl_cell(v):
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, (list, dict)):
        return str(v)
    return v


def to_json(o):
    if isinstance(o, dict):
        return {k: to_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [to_json(v) for v in o]
    if isinstance(o, ObjectId):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    return o
