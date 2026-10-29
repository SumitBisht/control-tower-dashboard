"""Pre-Shipment Inspection (PSI) module - one report per production lot.

MongoDB model (every row carries reportId/reportNo/reportDate/spvName/projectName/manufacturer/lotNo/uploadId):
  psi_reports   one doc per report: header, lot{lotNo,factory,sizePcs,sizeMwp}, wattClasses[], conclusion, signatories, summary   unique: reportNo
  psi_results   one doc per inspection/test row (standard, AQL, sampling, observation, decision, remarks)
  psi_nc        one doc per non-conformity (test, category, description, risk, count)
  psi_details   one doc per report: test conditions & equipment calibration, sun-simulator checks, maximum power rows + stats,
                per-test NC summaries / module lists, insulation, wet leakage, bi-faciality, mechanical loads, robustness, low irradiance
A lot re-issued under a new report number replaces the older one on the dashboard (latest report per project + lot wins).
Media in the Word file is never read, stored or served, and the original .docx is not kept (it contains the media).
"""
from datetime import datetime, timezone

from bson import ObjectId

from ..base import Column, Issue, ParseResult, ReportModule, UploadContext, WidgetDef
from .parser import parse_pre_shipment

COLLECTIONS = ("psi_results", "psi_nc", "psi_details")


class PreShipmentModule(ReportModule):
    key = "pre_shipment"
    title = "Pre-Shipment Inspection"
    widgets = [
        WidgetDef("kpi_lots", "Lots Inspected", "kpi"),
        WidgetDef("kpi_pass_rate", "Tests Passed", "kpi"),
        WidgetDef("kpi_ncs", "Non-Conformities", "kpi"),
        WidgetDef("kpi_power_dev", "Avg Power Difference", "kpi"),
        WidgetDef("lot_sizes", "Lot Size by Lot", "chart"),
        WidgetDef("lots", "Lots Inspected", "table", [
            Column("lot", "Lot"), Column("report_no", "Report No"), Column("report_date", "Report Date"), Column("product_type", "Product Type"),
            Column("lot_size", "Lot Size (pcs)"), Column("capacity_mwp", "Capacity (MWp)"), Column("tests", "Tests"),
            Column("non_conformities", "Non-Conformities"), Column("conclusion", "Conclusion")]),
        WidgetDef("results", "Inspection Result Summary", "table", [
            Column("lot", "Lot"), Column("test", "Inspection / Test"), Column("standard", "Standard / Reference"), Column("aql", "AQL"),
            Column("sampling", "Sampling"), Column("observation", "Observation"), Column("decision", "Decision"), Column("remarks", "Remarks")]),
        WidgetDef("nonconformities", "Non-Conformities", "table", [
            Column("lot", "Lot"), Column("test", "Test"), Column("category", "Category"), Column("description", "Description"),
            Column("risk", "Risk"), Column("count", "Count")]),
        WidgetDef("max_power", "Maximum Power Determination", "table", [
            Column("lot", "Lot"), Column("modules", "Modules Tested"), Column("avg_pre", "Avg Pmax Pre (Wp)"), Column("avg_during", "Avg Pmax During (Wp)"),
            Column("avg_diff_pct", "Avg Diff (%)"), Column("max_abs_diff_pct", "Max |Diff| (%)"), Column("out_of_tolerance", "Outside +/-1%")]),
        WidgetDef("equipment", "Test Equipment & Calibration", "table", [
            Column("lot", "Lot"), Column("test", "Test"), Column("equipment", "Equipment"), Column("serial_no", "Serial No"),
            Column("last_calibration", "Last Calibration"), Column("next_calibration", "Next Calibration"), Column("status", "Status")]),
    ]

    def parse(self, source, ctx: UploadContext) -> ParseResult:
        return parse_pre_shipment(source)

    async def check_duplicates(self, db, parsed, ctx: UploadContext) -> list[Issue]:
        issues = []
        rn = parsed["report"]["reportNo"]
        replace = ctx.options.get("replace")
        if await db.psi_reports.find_one({"reportNo": rn}):
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
        old = await db.psi_reports.find_one({"reportNo": rep["reportNo"]})
        if old:  # replace safely: park the old report, write the new one, delete the old one last
            await db.psi_reports.update_one({"_id": old["_id"]}, {"$set": {"reportNo": f"{rep['reportNo']}#replaced-{ctx.upload_id}"}})
        try:
            result = await self._write(db, parsed, spv, project, ctx)
        except BaseException:
            if old:
                await db.psi_reports.update_one({"_id": old["_id"]}, {"$set": {"reportNo": rep["reportNo"]}})
            raise
        if old:
            await self._delete_report(db, old["_id"])
        return result

    async def _write(self, db, parsed, spv, project, ctx: UploadContext) -> dict:
        rep, lot, s, now = parsed["report"], parsed["lot"], parsed["summary"], datetime.now(timezone.utc)
        report_id = (await db.psi_reports.insert_one({
            **{k: rep[k] for k in ("reportNo", "reportDate", "manufacturer", "location", "workshop", "signatories")},
            "client": rep["client"], "spvName": spv, "projectName": project, "lot": lot, "lotNo": lot["lotNo"],
            "wattClasses": parsed["wattClasses"], "wattTotal": parsed["wattTotal"], "conclusion": parsed["conclusion"], "summary": s,
            "uploadId": ctx.upload_id, "createdAt": now})).inserted_id
        common = {"reportId": report_id, "reportNo": rep["reportNo"], "reportDate": rep["reportDate"], "spvName": spv, "projectName": project,
                  "manufacturer": rep["manufacturer"], "lotNo": lot["lotNo"], "uploadId": ctx.upload_id}
        await db.psi_results.insert_many([{**common, **r} for r in parsed["results"]])
        if parsed["ncs"]:
            await db.psi_nc.insert_many([{**common, **n} for n in parsed["ncs"]])
        await db.psi_details.insert_one({**common, **parsed["details"], "createdAt": now})
        return {"reportNo": rep["reportNo"], "lotNo": lot["lotNo"], "modules": lot["sizePcs"], "tests": s["tests"], "ncTotal": s["ncTotal"],
                "spvName": spv, "projectName": project,
                "label": f"lot {lot['lotNo']}, {lot['sizePcs']:,} modules, {s['testsPassed']}/{s['tests']} tests passed, {s['ncTotal']} non-conformity"}

    async def _delete_report(self, db, report_id: ObjectId) -> None:
        for c in COLLECTIONS:
            await db[c].delete_many({"reportId": report_id})
        await db.psi_reports.delete_one({"_id": report_id})

    async def delete_upload_data(self, db, storage, upload_id: str) -> None:
        for c in COLLECTIONS:
            await db[c].delete_many({"uploadId": upload_id})
        await db.psi_reports.delete_many({"uploadId": upload_id})

    def router(self):
        from .router import build_router
        return build_router(self)

    async def ensure_indexes(self, db) -> None:
        await db.psi_reports.create_index("reportNo", unique=True)
        await db.psi_reports.create_index([("projectName", 1), ("lotNo", 1), ("reportDate", -1)])
        for c in ("psi_results", "psi_nc"):
            await db[c].create_index("reportId")
        for c in ("psi_results", "psi_nc", "psi_details"):
            await db[c].create_index("uploadId")
        await db.psi_details.create_index("reportId", unique=True)
        await db.psi_reports.create_index("uploadId")
