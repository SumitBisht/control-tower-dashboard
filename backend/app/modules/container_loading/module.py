from datetime import datetime, timezone

from bson import ObjectId

from ...core.config import get_settings
from ..base import Column, Issue, ParseResult, ReportModule, UploadContext, WidgetDef
from .parser import parse_container_loading

CHECKLIST_LABELS = {
    "weather": "Weather Conditions", "storage": "Storage Conditions", "packing": "Packing Quality",
    "loading": "Loading Quality", "packingListValidation": "Validation of Packing List",
    "outgoingQc": "Outgoing Quality Control", "shockLabel": "Shock Label Validations",
}


class ContainerLoadingModule(ReportModule):
    key = "container_loading"
    title = "Container Loading Monitoring"
    widgets = [
        WidgetDef("kpi_containers", "Total Containers", "kpi"),
        WidgetDef("kpi_modules", "Total Modules", "kpi"),
        WidgetDef("kpi_capacity", "Total Capacity", "kpi"),
        WidgetDef("kpi_result", "Inspection Result", "kpi"),
        WidgetDef("loading_trend", "Loading Trend by Date", "chart"),
        WidgetDef("product_summary", "Product-wise Summary", "table", [
            Column("product_type", "Product Type"), Column("containers", "No. of Containers"),
            Column("modules", "No. of Modules"), Column("capacity_mwp", "Total Capacity (MWp)")]),
        WidgetDef("recent_containers", "Recent Containers Loaded", "table", [
            Column("psi_lot", "PSI Lot/s"), Column("loading_date", "Date of Loading"), Column("product_type", "Product Type"),
            Column("containers_total", "No. of Containers - Total"), Column("containers_by_wp", "No. of Containers - by Wp"),
            Column("capacity_mwp", "Total Capacity (MWp)")]),
        WidgetDef("checklist_summary", "Inspection Checklist Summary", "checklist",
                  [Column("item", "Item"), Column("status", "Status")]),
    ]

    def parse(self, data: bytes, ctx: UploadContext) -> ParseResult:
        return parse_container_loading(data)

    async def check_duplicates(self, db, parsed, ctx: UploadContext) -> list[Issue]:
        issues = []
        rn = parsed["report"]["reportNo"]
        replace = ctx.options.get("replace")
        if await db.reports.find_one({"reportNo": rn}):
            if replace:
                issues.append(Issue("WARNING", "REPORT_REPLACED", f"Report {rn} already existed and was replaced."))
            else:
                issues.append(Issue("ERROR", "REPORT_DUPLICATE", f"Report {rn} already exists. Re-upload with 'Replace existing report' ticked to overwrite it."))
        dup = await db.uploads.find_one({"fileHash": ctx.file_hash, "status": {"$in": ["SUCCESS", "SUCCESS_WITH_WARNINGS"]}, "module": self.key})
        if dup and not replace:
            issues.append(Issue("ERROR", "FILE_DUPLICATE", "This exact file was already uploaded successfully."))
        return issues

    async def persist(self, db, storage, parsed, ctx: UploadContext) -> dict:
        rep, containers = parsed["report"], parsed["containers"]
        # precedence: upload-form value > configured CLIENT_NAME (property file / env) > name in the document
        spv = (ctx.options.get("spv_name") or get_settings().client_name or rep["client"].get("name") or "Unknown SPV").strip()
        project = (ctx.options.get("project_name") or rep["location"] or rep["client"].get("name") or "Unassigned").strip()

        old = await db.reports.find_one({"reportNo": rep["reportNo"]})
        if old:
            await self._delete_report(db, storage, old["_id"])

        now = datetime.now(timezone.utc)
        report_doc = {
            **{k: rep[k] for k in ("reportNo", "reportDate", "client", "manufacturer", "location", "workshop", "conclusion", "signatories", "lots")},
            "spvName": spv, "projectName": project, "uploadId": ctx.upload_id, "createdAt": now,
        }
        report_id = (await db.reports.insert_one(report_doc)).inserted_id

        for c in containers:
            await db.product_types.update_one(
                {"modelCode": c["modelCode"]},
                {"$setOnInsert": {"modelCode": c["modelCode"], "manufacturer": {"name": rep["manufacturer"]},
                                  "nominalPowerWp": c["nominalPowerWp"],
                                  "moduleDimMm": (c["inspection"] or {}).get("moduleDimMm")}},
                upsert=True)
        docs = []
        photo_count = 0
        for c in containers:
            photos = []
            for n, ph in enumerate(c.pop("photos", []), 1):
                key = f"photos/{report_id}/{c['srNo']}/{n}.{ph['ext']}"
                storage.save(key, ph["data"], ph["contentType"])
                photos.append({"label": ph["label"], "key": key})
                photo_count += 1
            docs.append({**c, "photos": photos, "reportId": report_id, "uploadId": ctx.upload_id, "spvName": spv,
                         "projectName": project, "manufacturer": rep["manufacturer"], "createdAt": now})
        if docs:
            await db.containers.insert_many(docs)
        return {"reportNo": rep["reportNo"], "containers": len(docs), "modules": sum(c["moduleQty"] for c in containers),
                "photos": photo_count, "spvName": spv, "projectName": project}

    async def _delete_report(self, db, storage, report_id: ObjectId) -> None:
        await db.containers.delete_many({"reportId": report_id})
        await db.reports.delete_one({"_id": report_id})
        storage.delete_prefix(f"photos/{report_id}")

    async def delete_upload_data(self, db, storage, upload_id: str) -> None:
        async for r in db.reports.find({"uploadId": upload_id}, {"_id": 1}):
            await self._delete_report(db, storage, r["_id"])
        await db.containers.delete_many({"uploadId": upload_id})

    def router(self):
        from .router import build_router
        return build_router(self)

    async def ensure_indexes(self, db) -> None:
        await db.reports.create_index("reportNo", unique=True)
        await db.reports.create_index([("projectName", 1), ("reportDate", -1)])
        await db.containers.create_index([("reportId", 1), ("containerNo", 1)], unique=True)
        await db.containers.create_index([("projectName", 1), ("loadingDate", 1)])
        await db.containers.create_index("uploadId")
        await db.product_types.create_index("modelCode", unique=True)
