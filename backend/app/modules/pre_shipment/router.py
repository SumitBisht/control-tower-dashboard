import csv
import io
import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...core.db import get_db
from ...deps import get_current_user
from ...widgets import get_widget_settings, table_payload
from ..common import d_str, latest_first, parse_day, to_json, xl_cell

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def report_match(spv=None, project=None, manufacturer=None, lot=None, date_from=None, date_to=None, q=None) -> dict:
    m: dict = {}
    for field, val in (("spvName", spv), ("projectName", project), ("manufacturer", manufacturer), ("lotNo", lot)):
        if val and val != "All":
            m[field] = val
    lo, hi = parse_day(date_from), parse_day(date_to, end=True)
    if lo and hi and lo > hi:
        raise HTTPException(422, "'From' date is after 'To' date")
    if lo or hi:
        m["reportDate"] = {**({"$gte": lo} if lo else {}), **({"$lte": hi} if hi else {})}
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        m["$or"] = [{f: rx} for f in ("reportNo", "spvName", "projectName", "manufacturer", "lotNo", "location")]
    return m


def params(spv: str | None = None, project: str | None = None, manufacturer: str | None = None, lot: str | None = None,
           date_from: str | None = None, date_to: str | None = None, q: str | None = None) -> dict:
    return report_match(spv, project, manufacturer, lot, date_from, date_to, q)


async def current_reports(db, match: dict) -> list[dict]:
    """Latest report per (project, lot): a re-issued lot report replaces the earlier one."""
    reps = await db.psi_reports.find(match).to_list(5000)
    return latest_first(reps, lambda r: (r["projectName"], r["lotNo"]))


def lot_key(r: dict):
    return (len(str(r["lotNo"])), str(r["lotNo"]))


def build_router(module) -> APIRouter:
    r = APIRouter(prefix=f"/{module.key}", tags=[module.key])

    @r.get("/filters")
    async def filters(user=Depends(get_current_user)):
        db = get_db()
        out = {}
        for key, field in (("spv", "spvName"), ("project", "projectName"), ("manufacturer", "manufacturer"), ("lot", "lotNo")):
            out[key] = sorted(await db.psi_reports.distinct(field), key=lambda x: (len(str(x)), str(x)))
        return out

    @r.get("/dashboard")
    async def dashboard(spv: str | None = None, project: str | None = None, manufacturer: str | None = None, lot: str | None = None,
                        date_from: str | None = None, date_to: str | None = None, user=Depends(get_current_user)):
        db = get_db()
        settings = await get_widget_settings(db, module)
        visible = {k for k, s in settings.items() if s["visible"]}
        cols = {k: {c for c, on in s["columns"].items() if on} for k, s in settings.items()}
        reps = sorted(await current_reports(db, report_match(spv, project, manufacturer, lot, date_from, date_to)), key=lot_key)
        ids = [x["_id"] for x in reps]
        by_id = {x["_id"]: x for x in reps}
        lot_of = lambda row: by_id[row["reportId"]]["lotNo"]  # noqa: E731
        S = lambda x, k: (x.get("summary") or {}).get(k) or 0  # noqa: E731

        w: dict = {}
        tests, passed = sum(S(x, "tests") for x in reps), sum(S(x, "testsPassed") for x in reps)
        if "kpi_lots" in visible:
            w["kpi_lots"] = {"value": len(reps), "modules": sum(S(x, "lotSizePcs") for x in reps), "mwp": round(sum(S(x, "lotSizeMwp") for x in reps), 4)}
        if "kpi_pass_rate" in visible:
            w["kpi_pass_rate"] = {"value": round(100 * passed / tests, 1) if tests else None, "passed": passed, "tests": tests}
        if "kpi_ncs" in visible:
            w["kpi_ncs"] = {"value": sum(S(x, "ncTotal") for x in reps), "major": sum(S(x, "ncMajor") for x in reps), "minor": sum(S(x, "ncMinor") for x in reps)}
        if "kpi_power_dev" in visible:
            diffs = [(x["summary"]["avgDiffPct"], S(x, "lotSizePcs")) for x in reps if (x.get("summary") or {}).get("avgDiffPct") is not None]
            w["kpi_power_dev"] = {"value": round(sum(d for d, _ in diffs) / len(diffs), 3) if diffs else None,
                                  "outOfTolerance": sum(S(x, "powerOutOfTolerance") for x in reps)}
        if "lot_sizes" in visible:
            w["lot_sizes"] = {"series": ["Modules"], "cumulative": False,
                              "data": [{"date": f"Lot {x['lotNo']}", "Modules": S(x, "lotSizePcs")} for x in reps]}
        if "lots" in visible:
            rows = [{"lot": x["lotNo"], "report_no": x["reportNo"], "report_date": d_str(x.get("reportDate")),
                     "product_type": ", ".join(sorted({c.get("productType") for c in x.get("wattClasses", []) if c.get("productType")})),
                     "lot_size": S(x, "lotSizePcs"), "capacity_mwp": (x.get("summary") or {}).get("lotSizeMwp"),
                     "tests": f"{S(x, 'testsPassed')} / {S(x, 'tests')} passed", "non_conformities": S(x, "ncTotal"), "conclusion": x.get("conclusion")}
                    for x in reps]
            w["lots"] = table_payload(module, "lots", rows, cols["lots"])
        if "results" in visible:
            res = await db.psi_results.find({"reportId": {"$in": ids}}).to_list(20000)
            res.sort(key=lambda x: (lot_key({"lotNo": lot_of(x)}), str(x["_id"])))
            rows = [{"lot": lot_of(x), "test": x["test"], "standard": x.get("standard"), "aql": x.get("aql"), "sampling": x.get("sampling"),
                     "observation": x.get("observation"), "decision": x.get("decision"), "remarks": x.get("remarks")} for x in res]
            w["results"] = table_payload(module, "results", rows, cols["results"])
        if "nonconformities" in visible:
            ncs = await db.psi_nc.find({"reportId": {"$in": ids}}).to_list(20000)
            ncs.sort(key=lambda x: (lot_key({"lotNo": lot_of(x)}), str(x["_id"])))
            rows = [{"lot": lot_of(x), "test": x["test"], "category": x.get("category"), "description": x.get("description"),
                     "risk": x.get("risk"), "count": x.get("count")} for x in ncs]
            w["nonconformities"] = table_payload(module, "nonconformities", rows, cols["nonconformities"])
        if "max_power" in visible:
            rows = []
            for x in reps:
                det = await db.psi_details.find_one({"reportId": x["_id"]}, {"maxPower.summary": 1})
                m = ((det or {}).get("maxPower") or {}).get("summary") or {}
                if m:
                    rows.append({"lot": x["lotNo"], "modules": m.get("modules"), "avg_pre": m.get("avgPre"), "avg_during": m.get("avgDuring"),
                                 "avg_diff_pct": m.get("avgDiffPct"), "max_abs_diff_pct": m.get("maxAbsDiffPct"), "out_of_tolerance": m.get("outOfTolerance")})
            w["max_power"] = table_payload(module, "max_power", rows, cols["max_power"])
        if "equipment" in visible:
            rows = []
            for x in reps:
                det = await db.psi_details.find_one({"reportId": x["_id"]}, {"testConditions": 1})
                for c in (det or {}).get("testConditions", []):
                    nxt = c.get("nextCalibration")
                    overdue = bool(nxt and x.get("reportDate") and nxt < x["reportDate"])
                    rows.append({"lot": x["lotNo"], "test": c["test"], "equipment": " ".join(filter(None, [c.get("manufacturer"), c.get("model")])),
                                 "serial_no": c.get("serialNo"), "last_calibration": d_str(c.get("lastCalibration")), "next_calibration": d_str(nxt),
                                 "status": "OVERDUE" if overdue else "OK"})
            w["equipment"] = table_payload(module, "equipment", rows, cols["equipment"])
        return {"widgets": w}

    # ------------------------------------------------------------------ reports tab
    @r.get("/reports")
    async def list_reports(match: dict = Depends(params), user=Depends(get_current_user)):
        rows = await get_db().psi_reports.find(match).sort([("reportDate", -1)]).limit(500).to_list(500)
        items = []
        for x in rows:
            s = x.get("summary") or {}
            items.append({"id": str(x["_id"]), "reportNo": x["reportNo"], "reportDate": d_str(x.get("reportDate")), "spvName": x.get("spvName"),
                          "projectName": x.get("projectName"), "manufacturer": x.get("manufacturer"), "workshop": x.get("workshop"),
                          "lotNo": x.get("lotNo"), "lotSizePcs": s.get("lotSizePcs"), "lotSizeMwp": s.get("lotSizeMwp"), "tests": s.get("tests"),
                          "testsPassed": s.get("testsPassed"), "testsFailed": s.get("testsFailed"), "ncTotal": s.get("ncTotal"),
                          "conclusion": x.get("conclusion")})
        return {"total": len(items), "items": items}

    @r.get("/reports/export")
    async def export(format: str = Query("xlsx", pattern="^(xlsx|csv)$"), match: dict = Depends(params), user=Depends(get_current_user)):
        db = get_db()
        reps = await db.psi_reports.find(match).sort([("reportDate", 1), ("lotNo", 1)]).limit(500).to_list(500)
        if not reps:
            raise HTTPException(404, "No reports match the selected filters")
        ids = [x["_id"] for x in reps]
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        res = await db.psi_results.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("lotNo", 1), ("_id", 1)]).to_list(20000)
        res_header = ["Report No", "Report Date", "SPV", "Project", "Lot", "Inspection/Test", "Standard / Reference", "AQL", "Sampling", "Observation", "Decision", "Remarks"]
        res_rows = [[x["reportNo"], d_str(x.get("reportDate")), x["spvName"], x["projectName"], x["lotNo"], x["test"], x.get("standard"), x.get("aql"),
                     x.get("sampling"), x.get("observation"), x.get("decision"), x.get("remarks")] for x in res]
        if format == "csv":
            buf = io.StringIO()
            wr = csv.writer(buf)
            wr.writerow(res_header)
            wr.writerows([["" if v is None else v for v in row] for row in res_rows])
            return Response(("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="pre-shipment-{stamp}.csv"'})
        from openpyxl import Workbook
        wb = Workbook(write_only=True)

        def sheet(name, header, rows):
            ws = wb.create_sheet(name[:31])
            ws.append(header)
            for row in rows:
                ws.append([xl_cell(v) for v in row])

        sheet("Reports", ["Report No", "Report Date", "SPV", "Project", "Manufacturer", "Workshop", "Lot", "Lot size (pcs)", "Lot size (MWp)", "Tests",
                          "Passed", "Failed", "Non-conformities", "Conclusion"],
              [[x["reportNo"], d_str(x.get("reportDate")), x["spvName"], x["projectName"], x["manufacturer"], x.get("workshop"), x["lotNo"],
                *[(x.get("summary") or {}).get(k) for k in ("lotSizePcs", "lotSizeMwp", "tests", "testsPassed", "testsFailed", "ncTotal")], x.get("conclusion")]
               for x in reps])
        sheet("Results", res_header, res_rows)
        ncs = await db.psi_nc.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("lotNo", 1)]).to_list(20000)
        sheet("Non-conformities", ["Report No", "Lot", "Test", "Category", "Description", "Risk", "Count"],
              [[x["reportNo"], x["lotNo"], x["test"], x.get("category"), x.get("description"), x.get("risk"), x.get("count")] for x in ncs])
        dets = await db.psi_details.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("lotNo", 1)]).to_list(500)
        sheet("Equipment", ["Report No", "Lot", "Test", "Applicable", "Process", "Manufacturer", "Model", "Serial No", "Last calibration", "Next calibration",
                            "Observation", "Evaluation"],
              [[d["reportNo"], d["lotNo"], c["test"], c.get("applicable"), c.get("process"), c.get("manufacturer"), c.get("model"), c.get("serialNo"),
                d_str(c.get("lastCalibration")), d_str(c.get("nextCalibration")), c.get("observation"), c.get("evaluation")]
               for d in dets for c in d.get("testConditions", [])])
        sheet("Max power", ["Report No", "Lot", "Sr", "Module No", "Pmax pre", "Vpm", "Ipm", "FF", "Pmax during", "Vpm", "Ipm", "FF", "Diff (Wp)", "Diff (%)", "Dimension"],
              [[d["reportNo"], d["lotNo"], m["srNo"], m["moduleNo"], m["pmax"], m["vpm"], m["ipm"], m["ff"], m["pmax1"], m["vpm1"], m["ipm1"], m["ff1"],
                m["diffWp"], m["diffPct"], m["dimension"]] for d in dets for m in ((d.get("maxPower") or {}).get("rows") or [])])
        for name, field in (("Sun-simulator checks", "calibration"), ("Insulation & ground", "insulation"), ("Wet leakage", "wetLeakage"),
                            ("Bi-faciality", "biFaciality"), ("Dynamic load", "dynamicLoad"), ("Static load", "staticLoad"),
                            ("Robustness", "robustness"), ("Low irradiance", "lowIrradiance")):
            keys: list[str] = []
            for d in dets:
                for rec in d.get(field, []):
                    keys += [k for k in rec if k not in keys]
            sheet(name, ["Report No", "Lot", *keys], [[d["reportNo"], d["lotNo"], *[rec.get(k) for k in keys]] for d in dets for rec in d.get(field, [])])
        out = io.BytesIO()
        wb.save(out)
        return Response(out.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="pre-shipment-{stamp}.xlsx"'})

    @r.get("/reports/{report_id}")
    async def report_detail(report_id: str, user=Depends(get_current_user)):
        db = get_db()
        try:
            rep = await db.psi_reports.find_one({"_id": ObjectId(report_id)})
        except InvalidId:
            rep = None
        if not rep:
            raise HTTPException(404, "Report not found")
        det = await db.psi_details.find_one({"reportId": rep["_id"]}) or {}
        strip = {"_id", "reportId", "uploadId", "createdAt"}
        return {"report": to_json({k: v for k, v in rep.items() if k != "uploadId"}),
                "details": to_json({k: v for k, v in det.items() if k not in strip}),
                "results": to_json(await db.psi_results.find({"reportId": rep["_id"]}, {"_id": 0, "reportId": 0, "uploadId": 0}).to_list(500)),
                "nonConformities": to_json(await db.psi_nc.find({"reportId": rep["_id"]}, {"_id": 0, "reportId": 0, "uploadId": 0}).to_list(500))}

    return r
