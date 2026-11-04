from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.db import get_db
from ...deps import get_current_user
from ...widgets import get_widget_settings, table_payload
from ..common import d_str, report_filter, table_download, to_json

SEARCH = ("reportNo", "spvName", "projectName", "manufacturer", "location", "workshop", "audit.factory", "audit.site")


def params(spv: str | None = None, project: str | None = None, manufacturer: str | None = None,
           date_from: str | None = None, date_to: str | None = None, q: str | None = None) -> dict:
    return report_filter({}, spv, project, manufacturer, date_from, date_to, q, SEARCH)


def build_router(module) -> APIRouter:
    r = APIRouter(prefix=f"/{module.key}", tags=[module.key])

    @r.get("/filters")
    async def filters(user=Depends(get_current_user)):
        db = get_db()
        return {key: sorted(await db.ppa_reports.distinct(field)) for key, field in (("spv", "spvName"), ("project", "projectName"), ("manufacturer", "manufacturer"))}

    @r.get("/dashboard")
    async def dashboard(match: dict = Depends(params), user=Depends(get_current_user)):
        db = get_db()
        settings = await get_widget_settings(db, module)
        visible = {k for k, s in settings.items() if s["visible"]}
        cols = {k: {c for c, on in s["columns"].items() if on} for k, s in settings.items()}
        reps = await db.ppa_reports.find(match).sort([("reportDate", -1), ("_id", -1)]).to_list(500)
        by_id = {x["_id"]: x for x in reps}
        ids = list(by_id)
        S = lambda x, k: (x.get("summary") or {}).get(k) or 0  # noqa: E731
        order = lambda x: (-by_id[x["reportId"]]["reportDate"].timestamp(), str(x["reportId"]), str(x["_id"]))  # noqa: E731
        checks_n, closed_n = sum(S(x, "checks") for x in reps), sum(S(x, "checksClosed") for x in reps)
        w: dict = {}
        if "kpi_ppa_audits" in visible:
            w["kpi_ppa_audits"] = {"value": len(reps), "latest": reps[0].get("conclusion") if reps else None, "latestDate": d_str(reps[0]["reportDate"]) if reps else None}
        if "kpi_ppa_checks" in visible:
            w["kpi_ppa_checks"] = {"value": round(100 * closed_n / checks_n, 1) if checks_n else None, "closed": closed_n, "checks": checks_n,
                                   "conditional": sum(S(x, "checksConditional") for x in reps)}
        if "kpi_ppa_nc" in visible:
            w["kpi_ppa_nc"] = {"value": sum(S(x, "ncTotal") for x in reps), "major": sum(S(x, "ncMajor") for x in reps), "minor": sum(S(x, "ncMinor") for x in reps)}
        if "kpi_ppa_open" in visible:
            w["kpi_ppa_open"] = {"value": sum(S(x, "ncOpen") for x in reps), "closed": sum(S(x, "ncClosed") for x in reps)}
        need_nc = visible & {"ppa_nc_trend", "ppa_nonconformities"}
        ncs = await db.ppa_nc.find({"reportId": {"$in": ids}}).to_list(20000) if need_nc else []
        if "ppa_nc_trend" in visible:
            by_date: dict = {}
            for n in ncs:
                e = by_date.setdefault(d_str(n.get("date")) or "Unknown", {"Major": 0, "Minor": 0})
                e[n.get("severity") if n.get("severity") in ("Major", "Minor") else "Minor"] += 1
            w["ppa_nc_trend"] = {"series": ["Major", "Minor"], "cumulative": False, "data": [{"date": d, **v} for d, v in sorted(by_date.items())]}
        if "ppa_audits" in visible:
            rows = [{"report_date": d_str(x["reportDate"]), "report_no": x["reportNo"], "factory": (x.get("audit") or {}).get("factory"), "site": (x.get("audit") or {}).get("site"),
                     "audit_type": (x.get("audit") or {}).get("type"), "sequence": (x.get("audit") or {}).get("sequence"), "audit_date": (x.get("audit") or {}).get("auditDate"),
                     "checks": f"{S(x, 'checksClosed')} / {S(x, 'checks')}", "non_conformities": f"{S(x, 'ncTotal')} ({S(x, 'ncOpen')} open)",
                     "conclusion": x.get("conclusion")} for x in reps]
            w["ppa_audits"] = table_payload(module, "ppa_audits", rows, cols["ppa_audits"])
        if "ppa_sections" in visible:
            rows = [{"report_date": d_str(x["reportDate"]), "section": name, "checks": s["checks"], "closed": s["closed"], "open": s["checks"] - s["closed"]}
                    for x in reps for name, s in ((x.get("extra") or {}).get("sections") or {}).items()]
            w["ppa_sections"] = table_payload(module, "ppa_sections", rows, cols["ppa_sections"])
        if "ppa_checks" in visible:
            chk = await db.ppa_checks.find({"reportId": {"$in": ids}}).to_list(20000)
            chk.sort(key=order)
            rows = [{"report_date": d_str(c["reportDate"]), "section": c["section"], "item": c["item"], "requirement": c.get("requirement"), "evidence": c.get("evidence"),
                     "status": c.get("status"), "note": c.get("statusNote")} for c in chk]
            w["ppa_checks"] = table_payload(module, "ppa_checks", rows, cols["ppa_checks"])
        if "ppa_nonconformities" in visible:
            ncs.sort(key=lambda n: (-by_id[n["reportId"]]["reportDate"].timestamp(), str(n["reportId"]), str(n.get("date")), str(n["_id"])))
            rows = [{"report_date": d_str(n["reportDate"]), "line": n.get("line"), "date": d_str(n.get("date")), "description": n["description"], "severity": n.get("severity"),
                     "process": n.get("process"), "status": n.get("status"), "note": n.get("statusNote")} for n in ncs]
            w["ppa_nonconformities"] = table_payload(module, "ppa_nonconformities", rows, cols["ppa_nonconformities"])
        return {"widgets": w}

    # ------------------------------------------------------------------ reports tab
    @r.get("/reports")
    async def list_reports(match: dict = Depends(params), user=Depends(get_current_user)):
        rows = await get_db().ppa_reports.find(match).sort([("reportDate", -1)]).limit(500).to_list(500)
        items = [{"id": str(x["_id"]), "reportNo": x["reportNo"], "reportDate": d_str(x.get("reportDate")), "spvName": x.get("spvName"),
                  "projectName": x.get("projectName"), "manufacturer": x.get("manufacturer"), "workshop": x.get("workshop"),
                  "auditDate": (x.get("audit") or {}).get("auditDate"), "conclusion": x.get("conclusion"), **(x.get("summary") or {})} for x in rows]
        return {"total": len(items), "items": items}

    @r.get("/reports/export")
    async def export(format: str = Query("xlsx", pattern="^(xlsx|csv)$"), match: dict = Depends(params), user=Depends(get_current_user)):
        db = get_db()
        reps = await db.ppa_reports.find(match).sort([("reportDate", 1)]).limit(500).to_list(500)
        if not reps:
            raise HTTPException(404, "No reports match the selected filters")
        ids = [x["_id"] for x in reps]
        chk = await db.ppa_checks.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("_id", 1)]).to_list(20000)
        ncs = await db.ppa_nc.find({"reportId": {"$in": ids}}).sort([("reportDate", 1), ("_id", 1)]).to_list(20000)
        s = lambda x, k: (x.get("summary") or {}).get(k)  # noqa: E731
        a = lambda x, k: (x.get("audit") or {}).get(k)  # noqa: E731
        return table_download(format, "pre-production-audit", [
            ("Checklist", ["Report No", "Report Date", "SPV", "Project", "Manufacturer", "Section", "Verification item", "Requirement", "Evidence / parameter", "Status", "Note"],
             [[c["reportNo"], d_str(c["reportDate"]), c["spvName"], c["projectName"], c["manufacturer"], c["section"], c["item"], c.get("requirement"),
               c.get("evidence"), c.get("status"), c.get("statusNote")] for c in chk]),
            ("Reports", ["Report No", "Report Date", "SPV", "Project", "Manufacturer", "Workshop", "Factory", "Site", "Audit type", "Sequence", "Audit date", "Checks",
                         "Checks closed", "Non-conformities", "Open non-conformities", "Conclusion"],
             [[x["reportNo"], d_str(x["reportDate"]), x["spvName"], x["projectName"], x["manufacturer"], x.get("workshop"), a(x, "factory"), a(x, "site"), a(x, "type"),
               a(x, "sequence"), a(x, "auditDate"), s(x, "checks"), s(x, "checksClosed"), s(x, "ncTotal"), s(x, "ncOpen"), x.get("conclusion")] for x in reps]),
            ("Non-conformities", ["Report No", "Report Date", "Workshop / line", "Date of finding", "Description", "Severity", "Process", "Closure status", "Note"],
             [[n["reportNo"], d_str(n["reportDate"]), n.get("line"), d_str(n.get("date")), n["description"], n.get("severity"), n.get("process"), n.get("status"),
               n.get("statusNote")] for n in ncs]),
        ])

    @r.get("/reports/{report_id}")
    async def report_detail(report_id: str, user=Depends(get_current_user)):
        db = get_db()
        try:
            rep = await db.ppa_reports.find_one({"_id": ObjectId(report_id)})
        except InvalidId:
            rep = None
        if not rep:
            raise HTTPException(404, "Report not found")
        strip = {"_id": 0, "reportId": 0, "uploadId": 0}
        return {"report": to_json({k: v for k, v in rep.items() if k != "uploadId"}),
                "checks": to_json(await db.ppa_checks.find({"reportId": rep["_id"]}, strip).to_list(500)),
                "nonConformities": to_json(await db.ppa_nc.find({"reportId": rep["_id"]}, strip).to_list(500))}

    return r
