"""Helpers shared by the report modules' routers."""
import re
import csv
import io
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import HTTPException, Response

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


def report_filter(fields: dict, spv=None, project=None, manufacturer=None, date_from=None, date_to=None, q=None, search=()) -> dict:
    """Mongo match for a report collection: exact SPV/project/manufacturer, reportDate range and a free-text search over `search` fields."""
    m: dict = {}
    for field, v in (("spvName", spv), ("projectName", project), ("manufacturer", manufacturer), *fields.items()):
        if v and v != "All":
            m[field] = v
    lo, hi = parse_day(date_from), parse_day(date_to, end=True)
    if lo and hi and lo > hi:
        raise HTTPException(422, "'From' date is after 'To' date")
    if lo or hi:
        m["reportDate"] = {**({"$gte": lo} if lo else {}), **({"$lte": hi} if hi else {})}
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        m["$or"] = [{f: rx} for f in search]
    return m


def header_fields(report: dict) -> dict:
    """The report-level fields every row of a simple (one-document-per-report) module carries for filtering."""
    return {k: report[k] for k in ("reportNo", "reportDate", "spvName", "projectName", "manufacturer", "uploadId") if k in report}


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def table_download(fmt: str, name: str, sheets: list[tuple[str, list, list[list]]]) -> Response:
    """Excel (one sheet per entry of `sheets`) or CSV (the first sheet only) download of (title, header, rows) tables."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if fmt == "csv":
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow(sheets[0][1])
        wr.writerows([["" if v is None else v for v in row] for row in sheets[0][2]])
        return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"'})
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    for title, header, rows in sheets:
        ws = wb.create_sheet(title[:31])
        ws.append(header)
        for row in rows:
            ws.append([xl_cell(v) for v in row])
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.xlsx"'})
