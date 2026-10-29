"""Production Supervision module (PV module manufacturing supervision reports).

MongoDB model (all rows carry reportId/reportNo/reportDate + spvName/projectName/manufacturer so every collection can be filtered directly):
  ps_reports        one doc per uploaded report (header, signatories, roll-up summary)           unique: reportNo
  ps_production     one doc per (report, date, power bin): planned/actual/deviation/day/night   idx: projectName,date,powerBin
  ps_qualification  one doc per (report, date) + one 'cumulative' doc per report: qualified bins, rejected, EL rework, suspected
  ps_nc             one doc per (report, non-conformity); `key` identifies the same NC across reports
  ps_details        one doc per report: BOM + storage conditions, IPQC, flasher, soldering, gel, dimension, RFID, lab tests, calibration, quality roll-up
Reports are cumulative (each one repeats earlier days), so dashboards read the LATEST report's version of each (project, date, bin) / NC.
Media (images/videos) in the Word file is never read, stored or served, and the original .docx is not kept (it contains the media).
"""
import re
from datetime import datetime, timezone

from bson import ObjectId

from ..base import Column, Issue, ParseResult, ReportModule, UploadContext, WidgetDef
from ..docx_utils import norm_key
from .parser import parse_production_supervision

COLLECTIONS = ("ps_production", "ps_qualification", "ps_nc", "ps_details")


class ProductionSupervisionModule(ReportModule):
    key = "production_supervision"
    title = "Production Supervision"
    widgets = [
        WidgetDef("kpi_output", "Total Actual Output", "kpi"),
        WidgetDef("kpi_achievement", "Plan Achievement", "kpi"),
        WidgetDef("kpi_rejected", "Rejected / Suspected Modules", "kpi"),
        WidgetDef("kpi_open_nc", "Open Non-Conformities", "kpi"),
        WidgetDef("production_trend", "Planned vs Actual Output", "chart"),
        WidgetDef("daily_production", "Daily Production", "table", [
            Column("date", "Date"), Column("power_bin", "Power Bin"), Column("planned", "Planned Output"), Column("actual", "Actual Output"),
            Column("deviation", "Deviation"), Column("day_shift", "Day Shift"), Column("night_shift", "Night Shift")]),
        WidgetDef("qualification", "Qualified & Rejected Modules", "table", [
            Column("date", "Date"), Column("qualified", "Qualified (by power bin)"), Column("rejected", "Rejected"),
            Column("el_rework_rejected", "EL Rework Rejected"), Column("suspected", "Suspected")]),
        WidgetDef("nonconformities", "Non-Conformities", "table", [
            Column("date", "Date of Finding"), Column("line", "Workshop / Line"), Column("description", "Description"),
            Column("severity", "Severity"), Column("process", "Process"), Column("affected_modules", "Affected Modules"),
            Column("status", "Status")]),
        WidgetDef("quality_checks", "Quality Checks (latest report)", "checklist", [
            Column("check", "Check"), Column("value", "Detail"), Column("status", "Status")]),
    ]

    def parse(self, source, ctx: UploadContext) -> ParseResult:
        return parse_production_supervision(source)

    async def check_duplicates(self, db, parsed, ctx: UploadContext) -> list[Issue]:
        issues = []
        rn = parsed["report"]["reportNo"]
        replace = ctx.options.get("replace")
        if await db.ps_reports.find_one({"reportNo": rn}):
            if replace:
                issues.append(Issue("WARNING", "REPORT_REPLACED", f"Report {rn} already existed and was replaced."))
            else:
                issues.append(Issue("ERROR", "REPORT_DUPLICATE", f"Report {rn} already exists. Re-upload with 'Replace existing report' ticked to overwrite it."))
        dup = await db.uploads.find_one({"fileHash": ctx.file_hash, "status": {"$in": ["SUCCESS", "SUCCESS_WITH_WARNINGS"]}, "module": self.key})
        if dup and not replace:
            issues.append(Issue("ERROR", "FILE_DUPLICATE", "This exact file was already uploaded successfully."))
        return issues

    async def persist(self, db, storage, parsed, ctx: UploadContext) -> dict:
        rep = parsed["report"]
        spv = (ctx.options.get("spv_name") or rep.get("spvName") or rep["client"].get("name") or "Unknown SPV").strip()
        project = (ctx.options.get("project_name") or rep.get("projectName") or rep["location"] or "Unassigned").strip()
        old = await db.ps_reports.find_one({"reportNo": rep["reportNo"]})
        if old:  # replace safely: park the old report, write the new one, delete the old one last
            await db.ps_reports.update_one({"_id": old["_id"]}, {"$set": {"reportNo": f"{rep['reportNo']}#replaced-{ctx.upload_id}"}})
        try:
            result = await self._write(db, parsed, spv, project, ctx)
        except BaseException:
            if old:
                await db.ps_reports.update_one({"_id": old["_id"]}, {"$set": {"reportNo": rep["reportNo"]}})
            raise
        if old:
            await self._delete_report(db, old["_id"])
        return result

    async def _write(self, db, parsed, spv, project, ctx: UploadContext) -> dict:
        rep, now = parsed["report"], datetime.now(timezone.utc)
        report_id = (await db.ps_reports.insert_one({
            **{k: rep[k] for k in ("reportNo", "reportDate", "manufacturer", "location", "workshop", "signatories")},
            "client": rep["client"], "spvName": spv, "projectName": project, "summary": parsed["summary"],
            "uploadId": ctx.upload_id, "createdAt": now})).inserted_id
        common = {"reportId": report_id, "reportNo": rep["reportNo"], "reportDate": rep["reportDate"], "spvName": spv,
                  "projectName": project, "manufacturer": rep["manufacturer"], "uploadId": ctx.upload_id}
        if parsed["production"]:
            await db.ps_production.insert_many([{**common, **r} for r in parsed["production"]])
        if parsed["qualification"]:
            await db.ps_qualification.insert_many([{**common, **q} for q in parsed["qualification"]])
        if parsed["nonConformities"]:
            await db.ps_nc.insert_many([{**common, **n, "key": nc_key(n)} for n in parsed["nonConformities"]])
        skip = {"production", "qualification", "nonConformities", "report", "summary"}
        await db.ps_details.insert_one({**common, **{k: v for k, v in parsed.items() if k not in skip}, "createdAt": now})
        s = parsed["summary"]
        return {"reportNo": rep["reportNo"], "days": s["days"], "modules": s["actualQty"], "openNcs": s["openNcs"],
                "spvName": spv, "projectName": project,
                "label": f"{s['days']} production day(s), {s['actualQty']:,} modules, {s['openNcs']} open NC"}

    async def _delete_report(self, db, report_id: ObjectId) -> None:
        for c in COLLECTIONS:
            await db[c].delete_many({"reportId": report_id})
        await db.ps_reports.delete_one({"_id": report_id})

    async def delete_upload_data(self, db, storage, upload_id: str) -> None:
        for c in COLLECTIONS:
            await db[c].delete_many({"uploadId": upload_id})
        await db.ps_reports.delete_many({"uploadId": upload_id})

    def router(self):
        from .router import build_router
        return build_router(self)

    async def ensure_indexes(self, db) -> None:
        await db.ps_reports.create_index("reportNo", unique=True)
        await db.ps_reports.create_index([("projectName", 1), ("reportDate", -1)])
        await db.ps_production.create_index([("projectName", 1), ("date", 1), ("powerBin", 1)])
        await db.ps_production.create_index("reportId")
        await db.ps_qualification.create_index([("projectName", 1), ("kind", 1), ("date", 1)])
        await db.ps_qualification.create_index("reportId")
        await db.ps_nc.create_index([("projectName", 1), ("key", 1)])
        await db.ps_nc.create_index("reportId")
        await db.ps_details.create_index("reportId", unique=True)
        for c in ("ps_production", "ps_qualification", "ps_nc", "ps_details", "ps_reports"):
            await db[c].create_index("uploadId")


def nc_key(n: dict) -> str:
    d = n.get("date")
    return (f"{d:%Y-%m-%d}" if d else "") + "|" + norm_key(n.get("process") or "")[:20] + "|" + norm_key(n.get("description") or "")[:60]
