"""Base class for report modules whose Word file is one report with a few child tables (BOM verification, pre-production audit).

A subclass names its collections and says how to turn parsed data into documents; this class provides duplicate checks,
the safe replace-by-report-number flow (park old report, write new, delete old last) and clean-up of a failed upload.
Media in the Word file is never read, stored or served, and the original .docx is not kept.
"""
from datetime import datetime, timezone

from bson import ObjectId

from .base import Issue, ReportModule, UploadContext


class SimpleReportModule(ReportModule):
    prefix: str  # collection prefix, e.g. "bom" -> bom_reports, bom_<child>
    children: tuple[str, ...]  # child collection suffixes, e.g. ("materials", "storage")
    noun = "report"

    @property
    def reports(self) -> str:
        return f"{self.prefix}_reports"

    def child_docs(self, parsed: dict) -> dict[str, list[dict]]:
        """{child suffix: [documents]} for this report."""
        raise NotImplementedError

    def label(self, parsed: dict) -> str:
        raise NotImplementedError

    async def check_duplicates(self, db, parsed, ctx: UploadContext) -> list[Issue]:
        issues, rn, replace = [], parsed["report"]["reportNo"], ctx.options.get("replace")
        if await db[self.reports].find_one({"reportNo": rn}):
            if replace:
                issues.append(Issue("WARNING", "REPORT_REPLACED", f"Report {rn} already existed and was replaced."))
            else:
                issues.append(Issue("ERROR", "REPORT_DUPLICATE", f"Report {rn} already exists. Re-upload with 'Replace existing report' ticked to overwrite it."))
        dup = await db.uploads.find_one({"fileHash": ctx.file_hash, "status": {"$in": ["SUCCESS", "SUCCESS_WITH_WARNINGS"]}, "module": self.key})
        if dup and not replace:
            issues.append(Issue("ERROR", "FILE_DUPLICATE", "This exact file was already uploaded successfully."))
        return issues

    async def persist(self, db, storage, parsed, ctx: UploadContext) -> dict:
        rep = dict(parsed["report"])
        rep["spvName"] = (ctx.options.get("spv_name") or rep.get("spvName") or "Unknown SPV").strip()
        rep["projectName"] = (ctx.options.get("project_name") or rep.get("projectName") or rep.get("location") or "Unassigned").strip()
        rep["uploadId"] = ctx.upload_id
        old = await db[self.reports].find_one({"reportNo": rep["reportNo"]})
        if old:
            await db[self.reports].update_one({"_id": old["_id"]}, {"$set": {"reportNo": f"{rep['reportNo']}#replaced-{ctx.upload_id}"}})
        try:
            report_id = (await db[self.reports].insert_one({**rep, "summary": parsed["summary"], "extra": parsed.get("extra", {}),
                                                            "createdAt": datetime.now(timezone.utc)})).inserted_id
            common = {"reportId": report_id, "reportNo": rep["reportNo"], "reportDate": rep["reportDate"], "spvName": rep["spvName"],
                      "projectName": rep["projectName"], "manufacturer": rep["manufacturer"], "uploadId": ctx.upload_id}
            for suffix, docs in self.child_docs(parsed).items():
                if docs:
                    await db[f"{self.prefix}_{suffix}"].insert_many([{**common, **d} for d in docs])
        except BaseException:
            if old:
                await db[self.reports].update_one({"_id": old["_id"]}, {"$set": {"reportNo": rep["reportNo"]}})
            raise
        if old:
            await self._delete_report(db, old["_id"])
        return {"reportNo": rep["reportNo"], "spvName": rep["spvName"], "projectName": rep["projectName"], "label": self.label(parsed), **parsed["summary"]}

    async def _delete_report(self, db, report_id: ObjectId) -> None:
        for c in self.children:
            await db[f"{self.prefix}_{c}"].delete_many({"reportId": report_id})
        await db[self.reports].delete_one({"_id": report_id})

    async def delete_upload_data(self, db, storage, upload_id: str) -> None:
        for c in self.children:
            await db[f"{self.prefix}_{c}"].delete_many({"uploadId": upload_id})
        await db[self.reports].delete_many({"uploadId": upload_id})

    async def ensure_indexes(self, db) -> None:
        await db[self.reports].create_index("reportNo", unique=True)
        await db[self.reports].create_index([("projectName", 1), ("reportDate", -1)])
        await db[self.reports].create_index("uploadId")
        for c in self.children:
            await db[f"{self.prefix}_{c}"].create_index("reportId")
            await db[f"{self.prefix}_{c}"].create_index("uploadId")
