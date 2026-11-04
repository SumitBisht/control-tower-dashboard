from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.db import get_db
from ...deps import get_current_user
from ...widgets import get_widget_settings, table_payload
from ..common import d_str, report_filter, table_download, to_json

SEARCH = ("reportNo", "spvName", "projectName", "manufacturer", "location", "workshop")


def params(spv: str | None = None, project: str | None = None, manufacturer: str | None = None,
           date_from: str | None = None, date_to: str | None = None, q: str | None = None) -> dict:
    return report_filter({}, spv, project, manufacturer, date_from, date_to, q, SEARCH)


def build_router(module) -> APIRouter:
    r = APIRouter(prefix=f"/{module.key}", tags=[module.key])

    @r.get("/filters")
    async def filters(user=Depends(get_current_user)):
        db = get_db()
        return {key: sorted(await db.bom_reports.distinct(field)) for key, field in (("spv", "spvName"), ("project", "projectName"), ("manufacturer", "manufacturer"))}

    @r.get("/dashboard")
    async def dashboard(match: dict = Depends(params), user=Depends(get_current_user)):
        db = get_db()
        settings = await get_widget_settings(db, module)
        visible = {k for k, s in settings.items() if s["visible"]}
        cols = {k: {c for c, on in s["columns"].items() if on} for k, s in settings.items()}
        reps = await db.bom_reports.find(match).sort([("reportDate", -1), ("_id", -1)]).to_list(500)
        by_id = {x["_id"]: x for x in reps}
        ids = list(by_id)
        S = lambda x, k: (x.get("summary") or {}).get(k) or 0  # noqa: E731
        latest = reps[0] if reps else None  # KPIs describe the most recent verification
        w: dict = {}
        if "kpi_bom_reports" in visible:
            w["kpi_bom_reports"] = {"value": len(reps), "latest": d_str(latest["reportDate"]) if latest else None}
        if "kpi_bom_pass" in visible:
            n = S(latest, "materials") if latest else 0
            w["kpi_bom_pass"] = {"value": round(100 * S(latest, "passed") / n, 1) if n else None, "passed": S(latest, "passed") if latest else 0, "materials": n,
                                 "underReview": S(latest, "underReview") if latest else 0}
        if "kpi_bom_deviations" in visible:
            w["kpi_bom_deviations"] = {"value": S(latest, "deviations") if latest else 0, "failed": S(latest, "failed") if latest else 0,
                                       "underReview": S(latest, "underReview") if latest else 0}
        if "kpi_bom_storage" in visible:
            n = S(latest, "storageItems") if latest else 0
            s = (latest or {}).get("summary") or {}
            w["kpi_bom_storage"] = {"value": round(100 * S(latest, "storagePassed") / n, 1) if n else None, "items": n, "issues": S(latest, "storageIssues") if latest else 0,
                                    "avgTempC": s.get("avgTempC"), "avgHumidityPct": s.get("avgHumidityPct")}
        if "bom_results" in visible:
            w["bom_results"] = {"series": ["Pass", "Under Review", "Fail"], "cumulative": False,
                                "data": [{"date": d_str(x["reportDate"]), "Pass": S(x, "passed"), "Under Review": S(x, "underReview"), "Fail": S(x, "failed")}
                                         for x in reversed(reps)]}
        if "bom_reports" in visible:
            rows = [{"report_date": d_str(x["reportDate"]), "report_no": x["reportNo"], "manufacturer": x.get("manufacturer"), "workshop": x.get("workshop"),
                     "materials": S(x, "materials"), "passed": S(x, "passed"), "under_review": S(x, "underReview"), "deviations": S(x, "deviations"),
                     "storage": f"{S(x, 'storagePassed')} / {S(x, 'storageItems')}"} for x in reps]
            w["bom_reports"] = table_payload(module, "bom_reports", rows, cols["bom_reports"])
        if "bom_materials" in visible:
            mats = await db.bom_materials.find({"reportId": {"$in": ids}}).to_list(20000)
            mats.sort(key=lambda m: (-by_id[m["reportId"]]["reportDate"].timestamp(), str(m["reportId"]), str(m["_id"])))
            rows = [{"report_date": d_str(m["reportDate"]), "material": m["material"], "bom_make": m.get("bomMake"), "actual_make": m.get("actualMake"),
                     "bom_origin": m.get("bomOrigin"), "actual_origin": m.get("actualOrigin"), "batch_no": m.get("batchNo"), "result": m.get("result"),
                     "remarks": m.get("remarks")} for m in mats]
            w["bom_materials"] = table_payload(module, "bom_materials", rows, cols["bom_materials"])
        if "bom_storage" in visible:
            st = await db.bom_storage.find({"reportId": {"$in": ids}}).to_list(20000)
            st.sort(key=lambda m: (-by_id[m["reportId"]]["reportDate"].timestamp(), str(m["reportId"]), str(m["_id"])))
            rows = [{"report_date": d_str(m["reportDate"]), "material": m["material"], "temperature": m.get("temperatureC"), "humidity": m.get("humidityPct"),
                     "expiry": m.get("expiry"), "observation": m.get("observation"), "result": m.get("result"), "remarks": m.get("remarks")} for m in st]
            w["bom_storage"] = table_payload(module, "bom_storage", rows, cols["bom_storage"])
        return {"widgets": w}

    # ------------------------------------------------------------------ reports tab
    @r.get("/reports")
    async def list_reports(match: dict = Depends(params), user=Depends(get_current_user)):
        rows = await get_db().bom_reports.find(match).sort([("reportDate", -1)]).limit(500).to_list(500)
        items = [{"id": str(x["_id"]), "reportNo": x["reportNo"], "reportDate": d_str(x.get("reportDate")), "spvName": x.get("spvName"),
                  "projectName": x.get("projectName"), "manufacturer": x.get("manufacturer"), "workshop": x.get("workshop"), **(x.get("summary") or {})}
                 for x in rows]
        return {"total": len(items), "items": items}

    @r.get("/reports/export")
    async def export(format: str = Query("xlsx", pattern="^(xlsx|csv)$"), match: dict = Depends(params), user=Depends(get_current_user)):
        db = get_db()
        reps = await db.bom_reports.find(match).sort([("reportDate", 1)]).limit(500).to_list(500)
        if not reps:
            raise HTTPException(404, "No reports match the selected filters")
        ids = [x["_id"] for x in reps]
        mats = await db.bom_materials.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("_id", 1)]).to_list(20000)
        st = await db.bom_storage.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("_id", 1)]).to_list(20000)
        s = lambda x, k: (x.get("summary") or {}).get(k)  # noqa: E731
        return table_download(format, "bom-verification", [
            ("Materials", ["Report No", "Report Date", "SPV", "Project", "Manufacturer", "Material", "Make & Model (BOM)", "Make & Model (Actual)", "Origin (BOM)",
                           "Origin (Actual)", "Batch No", "Result", "BOM deviation", "Remarks"],
             [[m["reportNo"], d_str(m["reportDate"]), m["spvName"], m["projectName"], m["manufacturer"], m["material"], m.get("bomMake"), m.get("actualMake"),
               m.get("bomOrigin"), m.get("actualOrigin"), m.get("batchNo"), m.get("result"), "Yes" if m.get("deviation") else "No", m.get("remarks")] for m in mats]),
            ("Reports", ["Report No", "Report Date", "SPV", "Project", "Manufacturer", "Workshop", "Materials", "Passed", "Under review", "Failed", "BOM deviations",
                         "Storage items", "Storage passed"],
             [[x["reportNo"], d_str(x["reportDate"]), x["spvName"], x["projectName"], x["manufacturer"], x.get("workshop"), s(x, "materials"), s(x, "passed"),
               s(x, "underReview"), s(x, "failed"), s(x, "deviations"), s(x, "storageItems"), s(x, "storagePassed")] for x in reps]),
            ("Storage", ["Report No", "Report Date", "Material", "Temperature (C)", "Humidity (%)", "Expiry", "Observation", "Result", "Remarks"],
             [[m["reportNo"], d_str(m["reportDate"]), m["material"], m.get("temperatureC"), m.get("humidityPct"), m.get("expiry"), m.get("observation"),
               m.get("result"), m.get("remarks")] for m in st]),
        ])

    @r.get("/reports/{report_id}")
    async def report_detail(report_id: str, user=Depends(get_current_user)):
        db = get_db()
        try:
            rep = await db.bom_reports.find_one({"_id": ObjectId(report_id)})
        except InvalidId:
            rep = None
        if not rep:
            raise HTTPException(404, "Report not found")
        strip = {"_id": 0, "reportId": 0, "uploadId": 0}
        return {"report": to_json({k: v for k, v in rep.items() if k != "uploadId"}),
                "materials": to_json(await db.bom_materials.find({"reportId": rep["_id"]}, strip).to_list(500)),
                "storage": to_json(await db.bom_storage.find({"reportId": rep["_id"]}, strip).to_list(500))}

    return r
