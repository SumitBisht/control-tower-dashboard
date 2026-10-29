"""Reports tab: search containers/reports, download the original Word report, export matching rows to Excel/CSV."""
import asyncio
import csv
import io
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...core.db import get_db
from ...core.storage import get_storage
from ...deps import get_current_user

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

CHECKLIST = [("weather", "Weather Conditions"), ("storage", "Storage Conditions"), ("packing", "Packing Quality"),
             ("loading", "Loading Quality"), ("packingListValidation", "Validation of Packing List"),
             ("outgoingQc", "Outgoing Quality Control"), ("shockLabel", "Shock Label Validations")]


def _d(v, time: bool = False):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M" if time else "%Y-%m-%d")
    return v


def _ship(c, k):
    return (c.get("shipment") or {}).get(k)


def _insp(c, k):
    return (c.get("inspection") or {}).get(k)


EXPORT_COLUMNS = [
    ("Report No", lambda c: c.get("reportNo")), ("SPV", lambda c: c.get("spvName")), ("Project", lambda c: c.get("projectName")),
    ("Manufacturer", lambda c: c.get("manufacturer")), ("PSI Lot", lambda c: c.get("psiLotNo")),
    ("Date of Loading", lambda c: _d(c.get("loadingDate"))), ("Sr No", lambda c: c.get("srNo")),
    ("Container No", lambda c: c.get("containerNo")), ("Seal No", lambda c: c.get("sealNo")),
    ("Product Type", lambda c: c.get("modelCode")), ("Nominal Power (Wp)", lambda c: c.get("nominalPowerWp")),
    ("Current Class", lambda c: c.get("currentClass")), ("Module Qty", lambda c: c.get("moduleQty")),
    ("Capacity (kWp)", lambda c: c.get("capacityKwp")), ("Container Size", lambda c: c.get("containerSize")),
    ("Warehousing Site", lambda c: _ship(c, "warehousingSite")),
    ("Truck Departure", lambda c: _d(_ship(c, "truckDeparture"), time=True)),
    ("Full Pallets", lambda c: _ship(c, "fullPallets")), ("Partial Pallets", lambda c: _ship(c, "partialPallets")),
    ("Inspection Result", lambda c: _insp(c, "result")), ("Non-Conformities", lambda c: _insp(c, "nonConformityCount")),
    ("Observation", lambda c: _insp(c, "observation")),
] + [(label, (lambda k: lambda c: (_insp(c, "checklist") or {}).get(k))(key)) for key, label in CHECKLIST]


def _parse_day(s: str | None, end: bool = False) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, f"Invalid date '{s}' (expected YYYY-MM-DD)")
    return d + timedelta(days=1) - timedelta(microseconds=1) if end else d


def build_match(date_from, date_to, spv, project, manufacturer, model, psi_lot, q) -> dict:
    m: dict = {}
    for field, val in (("spvName", spv), ("projectName", project), ("manufacturer", manufacturer), ("psiLots", psi_lot), ("modelCode", model)):
        if val and val != "All":
            m[field] = val
    lo, hi = _parse_day(date_from), _parse_day(date_to, end=True)
    if lo and hi and lo > hi:
        raise HTTPException(422, "'From' date is after 'To' date")
    if lo or hi:
        m["loadingDate"] = {**({"$gte": lo} if lo else {}), **({"$lte": hi} if hi else {})}
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        m["$or"] = [{f: rx} for f in ("reportNo", "containerNo", "sealNo", "spvName", "projectName", "modelCode", "manufacturer")]
    return m


def params(date_from: str | None = None, date_to: str | None = None, spv: str | None = None, project: str | None = None,
           manufacturer: str | None = None, model: str | None = None, psi_lot: str | None = None, q: str | None = None) -> dict:
    return build_match(date_from, date_to, spv, project, manufacturer, model, psi_lot, q)


def add_report_routes(r: APIRouter) -> None:
    @r.get("/reports")
    async def list_reports(match: dict = Depends(params), user=Depends(get_current_user)):
        db = get_db()
        groups = await (await db.containers.aggregate([
            {"$match": match},
            {"$group": {"_id": "$reportId", "containers": {"$sum": 1}, "modules": {"$sum": "$moduleQty"},
                        "capacityKwp": {"$sum": "$capacityKwp"}, "models": {"$addToSet": "$modelCode"},
                        "first": {"$min": "$loadingDate"}, "last": {"$max": "$loadingDate"},
                        "failed": {"$sum": {"$cond": [{"$eq": ["$inspection.result", "FAIL"]}, 1, 0]}}}},
            {"$sort": {"last": -1}}, {"$limit": 500}])).to_list(500)
        reports = {d["_id"]: d async for d in db.reports.find({"_id": {"$in": [g["_id"] for g in groups]}})}
        items = []
        for g in groups:
            rep = reports.get(g["_id"])
            if not rep:
                continue
            items.append({
                "id": str(rep["_id"]), "reportNo": rep["reportNo"], "reportDate": _d(rep.get("reportDate")),
                "spvName": rep.get("spvName"), "projectName": rep.get("projectName"), "manufacturer": rep.get("manufacturer"),
                "conclusion": rep.get("conclusion"), "models": sorted(g["models"]), "containers": g["containers"],
                "modules": g["modules"], "capacityMwp": round(g["capacityKwp"] / 1000, 3), "failedContainers": g["failed"],
                "loadingFrom": _d(g["first"]), "loadingTo": _d(g["last"]), "hasSource": bool(rep.get("sourceKey")),
                "sourceFileName": rep.get("sourceFileName")})
        return {"total": len(items), "items": items}

    @r.get("/reports/export")
    async def export(format: str = Query("xlsx", pattern="^(xlsx|csv)$"), match: dict = Depends(params), user=Depends(get_current_user)):
        rows = await get_db().containers.find(match, {"photos": 0}).sort([("loadingDate", 1), ("reportNo", 1), ("srNo", 1)]).limit(50000).to_list(50000)
        if not rows:
            raise HTTPException(404, "No containers match the selected filters")
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        header = [h for h, _ in EXPORT_COLUMNS]
        data = [[get(c) for _, get in EXPORT_COLUMNS] for c in rows]
        if format == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(header)
            w.writerows([["" if v is None else v for v in row] for row in data])
            return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="container-loading-{stamp}.csv"'})
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        ws = wb.create_sheet("Containers")
        ws.append(header)
        for row in data:
            ws.append(row)
        out = io.BytesIO()
        wb.save(out)
        return Response(out.getvalue(), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="container-loading-{stamp}.xlsx"'})

    @r.get("/reports/{report_id}/download")
    async def download(report_id: str, user=Depends(get_current_user)):
        try:
            rep = await get_db().reports.find_one({"_id": ObjectId(report_id)})
        except InvalidId:
            rep = None
        if not rep:
            raise HTTPException(404, "Report not found")
        if not rep.get("sourceKey"):
            raise HTTPException(404, "The original document is not available for this report")
        try:
            data = await asyncio.to_thread(get_storage().load, rep["sourceKey"])
        except Exception:  # noqa: BLE001
            raise HTTPException(404, "The original document could not be retrieved from storage")
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", rep.get("sourceFileName") or f"{rep['reportNo']}.docx")
        return Response(data, media_type=DOCX, headers={"Content-Disposition": f'attachment; filename="{name}"'})
