import csv
import io
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...core.db import get_db
from ...deps import get_current_user
from ...widgets import get_widget_settings, table_payload
from ..common import d_str as _d, latest_first, parse_day as _day, to_json as _json, xl_cell as _cell

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FETCH_LIMIT = 50000






def common_filters(spv: str | None = None, project: str | None = None, manufacturer: str | None = None) -> dict:
    m: dict = {}
    for field, val in (("spvName", spv), ("projectName", project), ("manufacturer", manufacturer)):
        if val and val != "All":
            m[field] = val
    return m


def date_range(date_from: str | None, date_to: str | None) -> dict | None:
    lo, hi = _day(date_from), _day(date_to, end=True)
    if lo and hi and lo > hi:
        raise HTTPException(422, "'From' date is after 'To' date")
    if not (lo or hi):
        return None
    return {**({"$gte": lo} if lo else {}), **({"$lte": hi} if hi else {})}




def qm(v: dict | None) -> dict | None:
    return None if v is None else {"qty": v.get("qty"), "mwp": v.get("mwp")}


def build_router(module) -> APIRouter:
    r = APIRouter(prefix=f"/{module.key}", tags=[module.key])

    @r.get("/filters")
    async def filters(user=Depends(get_current_user)):
        db = get_db()
        out = {}
        for key, field in (("spv", "spvName"), ("project", "projectName"), ("manufacturer", "manufacturer")):
            out[key] = sorted(await db.ps_production.distinct(field))
        out["power_bin"] = [str(b) for b in sorted(b for b in await db.ps_production.distinct("powerBin") if b is not None)]
        return out

    @r.get("/dashboard")
    async def dashboard(spv: str | None = None, project: str | None = None, manufacturer: str | None = None, power_bin: str | None = None,
                        date_from: str | None = None, date_to: str | None = None, user=Depends(get_current_user)):
        db = get_db()
        settings = await get_widget_settings(db, module)
        visible = {k for k, s in settings.items() if s["visible"]}
        cols = {k: {c for c, on in s["columns"].items() if on} for k, s in settings.items()}
        base = common_filters(spv, project, manufacturer)
        rng = date_range(date_from, date_to)

        prod_q = dict(base)
        if power_bin and power_bin != "All":
            prod_q["powerBin"] = int(power_bin) if power_bin.isdigit() else power_bin
        if rng:
            prod_q["date"] = rng
        prod = latest_first(await db.ps_production.find(prod_q).to_list(FETCH_LIMIT), lambda x: (x["projectName"], x["date"], x["powerBin"]))
        prod.sort(key=lambda x: (x["date"], x["powerBin"] or 0))

        def tot(rows, grp, f):
            return sum(((x.get(grp) or {}).get(f) or 0) for x in rows)
        planned, actual = tot(prod, "planned", "qty"), tot(prod, "actual", "qty")

        w: dict = {}
        if "kpi_output" in visible:
            w["kpi_output"] = {"value": actual, "mwp": round(tot(prod, "actual", "mwp"), 3), "unit": "pcs"}
        if "kpi_achievement" in visible:
            w["kpi_achievement"] = {"value": round(100 * actual / planned, 1) if planned else None, "planned": planned, "actual": actual, "unit": "%"}
        if "kpi_rejected" in visible:
            cum = latest_first(await db.ps_qualification.find({**base, "kind": "cumulative"}).to_list(FETCH_LIMIT), lambda x: x["projectName"])
            rej = sum(((c.get("rejected") or {}).get("qty") or 0) for c in cum)
            sus = sum(((c.get("suspected") or {}).get("qty") or 0) for c in cum)
            w["kpi_rejected"] = {"value": rej + sus, "rejected": rej, "suspected": sus}
        if "kpi_open_nc" in visible or "nonconformities" in visible:
            nc_q = dict(base)
            if rng:
                nc_q["date"] = rng
            ncs = latest_first(await db.ps_nc.find(nc_q).to_list(FETCH_LIMIT), lambda x: (x["projectName"], x["key"]))
            ncs.sort(key=lambda x: x.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            if "kpi_open_nc" in visible:
                w["kpi_open_nc"] = {"value": sum(1 for n in ncs if n["status"] == "OPEN"), "total": len(ncs)}
            if "nonconformities" in visible:
                rows = [{"date": _d(n.get("date")), "line": n.get("line"), "description": n.get("description"), "severity": n.get("severity"),
                         "process": n.get("process"), "affected_modules": n.get("affectedModules"), "status": n["status"]} for n in ncs]
                w["nonconformities"] = table_payload(module, "nonconformities", rows, cols["nonconformities"])
        if "production_trend" in visible:
            by_date: dict = {}
            for x in prod:
                e = by_date.setdefault(_d(x["date"]), {"Planned": 0, "Actual": 0})
                e["Planned"] += (x.get("planned") or {}).get("qty") or 0
                e["Actual"] += (x.get("actual") or {}).get("qty") or 0
            w["production_trend"] = {"series": ["Planned", "Actual"], "cumulative": False,
                                     "data": [{"date": d, **v} for d, v in sorted(by_date.items())]}
        if "daily_production" in visible:
            rows = [{"date": _d(x["date"]), "power_bin": f"{x['powerBin']} Wp" if x.get("powerBin") else None,
                     "planned": qm(x.get("planned")), "actual": qm(x.get("actual")), "deviation": qm(x.get("deviation")),
                     "day_shift": qm(x.get("day")), "night_shift": qm(x.get("night"))} for x in reversed(prod)]
            w["daily_production"] = table_payload(module, "daily_production", rows, cols["daily_production"])
        if "qualification" in visible:
            q_q = dict(base)
            if rng:
                q_q["date"] = rng
            q_all = await db.ps_qualification.find({**q_q, "kind": "daily"}).to_list(FETCH_LIMIT)
            daily = latest_first(q_all, lambda x: (x["projectName"], x["date"]))
            daily.sort(key=lambda x: x["date"], reverse=True)
            cum = latest_first(await db.ps_qualification.find({**base, "kind": "cumulative"}).to_list(FETCH_LIMIT), lambda x: x["projectName"])
            rows = [{"date": _d(x["date"]), "qualified": {b: qm(v) for b, v in (x.get("qualified") or {}).items()}, "rejected": qm(x.get("rejected")),
                     "el_rework_rejected": qm(x.get("elReworkRejected")), "suspected": qm(x.get("suspected"))} for x in daily]
            if cum and not rng:
                merged = {"qualified": {}, "rejected": {"qty": 0, "mwp": 0.0}, "el_rework_rejected": {"qty": 0, "mwp": 0.0}, "suspected": {"qty": 0, "mwp": 0.0}}
                for c in cum:  # one cumulative row per project; sum when several projects are in scope
                    for b, v in (c.get("qualified") or {}).items():
                        e = merged["qualified"].setdefault(b, {"qty": 0, "mwp": 0.0})
                        e["qty"] += (v or {}).get("qty") or 0
                        e["mwp"] += (v or {}).get("mwp") or 0
                    for src, dst in (("rejected", "rejected"), ("elReworkRejected", "el_rework_rejected"), ("suspected", "suspected")):
                        merged[dst]["qty"] += (c.get(src) or {}).get("qty") or 0
                        merged[dst]["mwp"] += (c.get(src) or {}).get("mwp") or 0
                rows.append({"date": "Cumulative", **merged})
            w["qualification"] = table_payload(module, "qualification", rows, cols["qualification"])
        if "quality_checks" in visible:
            reps = await db.ps_reports.find(base).sort("reportDate", -1).limit(1).to_list(1)
            rows, src = [], None
            if reps:
                det = await db.ps_details.find_one({"reportId": reps[0]["_id"]}, {"quality": 1})
                src = reps[0]["reportNo"]
                rows = [{"check": q["label"], "value": q["value"], "status": q["status"]} for q in (det or {}).get("quality", [])]
            t = table_payload(module, "quality_checks", rows, cols["quality_checks"])
            t["source"] = src
            w["quality_checks"] = t
        return {"widgets": w}

    # ------------------------------------------------------------------ reports tab
    def report_params(date_from: str | None = None, date_to: str | None = None, spv: str | None = None, project: str | None = None,
                      manufacturer: str | None = None, q: str | None = None) -> dict:
        m = common_filters(spv, project, manufacturer)
        lo, hi = _day(date_from), _day(date_to, end=True)
        if lo and hi and lo > hi:
            raise HTTPException(422, "'From' date is after 'To' date")
        if lo:
            m["summary.lastDate"] = {"$gte": lo}  # report covers production on/after 'from'
        if hi:
            m["summary.firstDate"] = {"$lte": hi}
        if q and q.strip():
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            m["$or"] = [{f: rx} for f in ("reportNo", "spvName", "projectName", "manufacturer", "workshop", "location")]
        return m

    @r.get("/reports")
    async def list_reports(match: dict = Depends(report_params), user=Depends(get_current_user)):
        rows = await get_db().ps_reports.find(match).sort("reportDate", -1).limit(500).to_list(500)
        items = []
        for x in rows:
            s = x.get("summary") or {}
            items.append({"id": str(x["_id"]), "reportNo": x["reportNo"], "reportDate": _d(x.get("reportDate")), "spvName": x.get("spvName"),
                          "projectName": x.get("projectName"), "manufacturer": x.get("manufacturer"), "workshop": x.get("workshop"),
                          "firstDate": _d(s.get("firstDate")), "lastDate": _d(s.get("lastDate")), "days": s.get("days"),
                          "plannedQty": s.get("plannedQty"), "actualQty": s.get("actualQty"), "actualMwp": s.get("actualMwp"),
                          "rejectedQty": s.get("rejectedQty"), "suspectedQty": s.get("suspectedQty"), "openNcs": s.get("openNcs"),
                          "bomDiffer": s.get("bomDiffer"), "ipqcFail": s.get("ipqcFail")})
        return {"total": len(items), "items": items}

    @r.get("/reports/export")
    async def export(format: str = Query("xlsx", pattern="^(xlsx|csv)$"), match: dict = Depends(report_params), user=Depends(get_current_user)):
        db = get_db()
        reps = await db.ps_reports.find(match).sort("reportDate", 1).limit(500).to_list(500)
        if not reps:
            raise HTTPException(404, "No reports match the selected filters")
        ids = [x["_id"] for x in reps]
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        prod = await db.ps_production.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("date", 1), ("powerBin", 1)]).to_list(FETCH_LIMIT)

        def flat(x, g):
            v = x.get(g) or {}
            return v.get("qty"), v.get("mwp")
        prod_header = ["Report No", "SPV", "Project", "Manufacturer", "Date", "Power Bin (Wp)", "Planned (pcs)", "Planned (MWp)", "Actual (pcs)", "Actual (MWp)",
                       "Deviation (pcs)", "Deviation (MWp)", "Day shift (pcs)", "Day shift (MWp)", "Night shift (pcs)", "Night shift (MWp)"]
        prod_rows = [[x["reportNo"], x["spvName"], x["projectName"], x["manufacturer"], _d(x["date"]), x.get("powerBin"),
                      *flat(x, "planned"), *flat(x, "actual"), *flat(x, "deviation"), *flat(x, "day"), *flat(x, "night")] for x in prod]
        if format == "csv":
            buf = io.StringIO()
            wr = csv.writer(buf)
            wr.writerow(prod_header)
            wr.writerows([["" if v is None else v for v in row] for row in prod_rows])
            return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="production-supervision-{stamp}.csv"'})

        from openpyxl import Workbook
        wb = Workbook(write_only=True)

        def sheet(name, header, rows):
            ws = wb.create_sheet(name[:31])
            ws.append(header)
            for row in rows:
                ws.append([_cell(v) for v in row])

        sheet("Reports", ["Report No", "Report Date", "SPV", "Project", "Manufacturer", "Workshop", "Location", "Production from", "Production to", "Days",
                          "Planned (pcs)", "Actual (pcs)", "Actual (MWp)", "Rejected (cum.)", "Suspected (cum.)", "Open NCs", "BOM lines differing", "IPQC fails"],
              [[x["reportNo"], _d(x.get("reportDate")), x["spvName"], x["projectName"], x["manufacturer"], x.get("workshop"), x.get("location"),
                _d((x.get("summary") or {}).get("firstDate")), _d((x.get("summary") or {}).get("lastDate")), *[(x.get("summary") or {}).get(k) for k in
                ("days", "plannedQty", "actualQty", "actualMwp", "rejectedQty", "suspectedQty", "openNcs", "bomDiffer", "ipqcFail")]] for x in reps])
        sheet("Production", prod_header, prod_rows)
        qual = await db.ps_qualification.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("kind", 1), ("date", 1)]).to_list(FETCH_LIMIT)
        bins = sorted({b for x in qual for b in (x.get("qualified") or {})})
        sheet("Qualification", ["Report No", "Row", "Date", *[f"{b} Wp qualified (pcs)" for b in bins], *[f"{b} Wp qualified (MWp)" for b in bins],
                                "Rejected (pcs)", "Rejected (MWp)", "EL rework rejected (pcs)", "EL rework rejected (MWp)", "Suspected (pcs)", "Suspected (MWp)"],
              [[x["reportNo"], x["kind"], _d(x.get("date")), *[((x.get("qualified") or {}).get(b) or {}).get("qty") for b in bins],
                *[((x.get("qualified") or {}).get(b) or {}).get("mwp") for b in bins], *flat(x, "rejected"), *flat(x, "elReworkRejected"),
                *flat(x, "suspected")] for x in qual])
        ncs = await db.ps_nc.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("date", 1)]).to_list(FETCH_LIMIT)
        sheet("Non-conformities", ["Report No", "Date of finding", "Workshop/Line", "Description", "Severity", "Process", "Affected modules", "Control type",
                                   "Vendor action", "Closure status", "Status", "Shift", "Additional details", "Closed immediately?"],
              [[x["reportNo"], _d(x.get("date")), x.get("line"), x.get("description"), x.get("severity"), x.get("process"), x.get("affectedModules"),
                x.get("controlType"), x.get("vendorAction"), x.get("closureStatus"), x["status"], x.get("shift"), x.get("additionalDetails"),
                x.get("closedImmediately")] for x in ncs])
        dets = await db.ps_details.find({"reportId": {"$in": ids}}).sort("reportDate", 1).to_list(500)
        sheet("BOM", ["Report No", "Line", "Shift", "Material", "Make & model (BOM)", "Make & model (actual)", "Origin (BOM)", "Origin (actual)", "Batch no",
                      "Result", "Remarks", "Make matches BOM", "Origin matches BOM"],
              [[d["reportNo"], b.get("line"), b.get("shift"), m["material"], m["makeBom"], m["makeActual"], m["originBom"], m["originActual"], m["batchNo"],
                m["result"], m["remarks"], m["makeMatches"], m["originMatches"]] for d in dets for b in d.get("bom", []) for m in b["materials"]])
        sheet("Material storage", ["Report No", "Line", "Shift", "Material", "Temperature (C)", "Humidity (%)", "Expiry", "Observations", "Result", "Remarks"],
              [[d["reportNo"], b.get("line"), b.get("shift"), s["material"], s["temperatureC"], s["humidityPct"], s["expiry"], s["observations"], s["result"],
                s["remarks"]] for d in dets for b in d.get("bom", []) for s in b["storage"]])
        sheet("IPQC", ["Report No", "Process", "IPQC check", "Parameters", "Qty tested", "Test result", "Inspection result", "Line", "Remarks"],
              [[d["reportNo"], i["process"], i["check"], i["parameters"], i["qtyTested"], i["testResult"], i["result"], i["line"], i["remarks"]]
               for d in dets for i in d.get("ipqc", [])])
        for sheet_name, field in (("Flasher results", "flasherResults"), ("Gel content", "gel"), ("Dimension check", "dimension"), ("RFID check", "rfid"),
                                  ("Finished storage", "finishedStorage"), ("Data verification", "dataVerification"), ("Calibration", "firstMeasurement")):
            keys: list[str] = []
            for d in dets:
                for rec in d.get(field, []):
                    keys += [k for k in rec if k not in keys]
            sheet(sheet_name, ["Report No", *keys], [[d["reportNo"], *[rec.get(k) for k in keys]] for d in dets for rec in d.get(field, [])])
        sheet("Soldering peel", ["Report No", "Line", "Shift", "Date", *[f"Front {i}" for i in range(1, 8)], *[f"Rear {i}" for i in range(1, 8)]],
              [[d["reportNo"], s.get("line"), s.get("shift"), _d(s.get("date")), *(s.get("front") + [None] * 7)[:7], *(s.get("rear") + [None] * 7)[:7]]
               for d in dets for s in d.get("soldering", [])])
        out = io.BytesIO()
        wb.save(out)
        return Response(out.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="production-supervision-{stamp}.xlsx"'})

    @r.get("/reports/{report_id}")
    async def report_detail(report_id: str, user=Depends(get_current_user)):
        db = get_db()
        try:
            rep = await db.ps_reports.find_one({"_id": ObjectId(report_id)})
        except InvalidId:
            rep = None
        if not rep:
            raise HTTPException(404, "Report not found")
        det = await db.ps_details.find_one({"reportId": rep["_id"]}) or {}
        strip = {"_id", "reportId", "uploadId", "createdAt"}
        return {"report": _json({k: v for k, v in rep.items() if k not in {"uploadId"}}),
                "details": _json({k: v for k, v in det.items() if k not in strip}),
                "production": _json(await db.ps_production.find({"reportId": rep["_id"]}, {"_id": 0, "reportId": 0, "uploadId": 0}).to_list(5000)),
                "qualification": _json(await db.ps_qualification.find({"reportId": rep["_id"]}, {"_id": 0, "reportId": 0, "uploadId": 0}).to_list(5000)),
                "nonConformities": _json(await db.ps_nc.find({"reportId": rep["_id"]}, {"_id": 0, "reportId": 0, "uploadId": 0}).to_list(5000))}

    return r




