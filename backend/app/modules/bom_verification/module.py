"""BOM Verification (store) module - one report per verification visit.

MongoDB model (every row carries reportId/reportNo/reportDate/spvName/projectName/manufacturer/uploadId):
  bom_reports    one doc per report: header (client, SPV, project, manufacturer, location, workshop), summary counts   unique: reportNo
  bom_materials  one doc per material: BOM vs actual make/model and country of origin, batch no, result, remarks, deviation flags
  bom_storage    one doc per stored material: temperature, humidity, expiry, observation, result, remarks
Every verification report is kept (batches change between visits), so the dashboard shows all reports matching the filters.
Media in the Word file is never read, stored or served, and the original .docx is not kept.
"""
from ..base import Column, ParseResult, UploadContext, WidgetDef
from ..simple import SimpleReportModule
from .parser import parse_bom_verification


class BomVerificationModule(SimpleReportModule):
    key = "bom_verification"
    title = "BOM Assessment"
    prefix = "bom"
    children = ("materials", "storage")
    widgets = [
        WidgetDef("kpi_bom_reports", "Verifications", "kpi"),
        WidgetDef("kpi_bom_pass", "Materials Passed", "kpi"),
        WidgetDef("kpi_bom_deviations", "BOM Deviations", "kpi"),
        WidgetDef("kpi_bom_storage", "Storage Conditions OK", "kpi"),
        WidgetDef("bom_results", "Material Results by Verification", "chart"),
        WidgetDef("bom_reports", "Verification Reports", "table", [
            Column("report_date", "Report Date"), Column("report_no", "Report No"), Column("manufacturer", "Manufacturer"), Column("workshop", "Workshop"),
            Column("materials", "Materials"), Column("passed", "Passed"), Column("under_review", "Under Review"), Column("deviations", "BOM Deviations"),
            Column("storage", "Storage OK")]),
        WidgetDef("bom_materials", "Bill of Materials Verification", "table", [
            Column("report_date", "Report Date"), Column("material", "Material"), Column("bom_make", "Make & Model (BOM)"), Column("actual_make", "Make & Model (Actual)"),
            Column("bom_origin", "Origin (BOM)"), Column("actual_origin", "Origin (Actual)"), Column("batch_no", "Batch No"),
            Column("result", "Result"), Column("remarks", "Remarks")]),
        WidgetDef("bom_storage", "Materials Storage Conditions", "table", [
            Column("report_date", "Report Date"), Column("material", "Material"), Column("temperature", "Temperature (°C)"), Column("humidity", "Humidity (%)"),
            Column("expiry", "Expiry"), Column("observation", "Observation"), Column("result", "Result"), Column("remarks", "Remarks")]),
    ]

    def parse(self, source, ctx: UploadContext) -> ParseResult:
        return parse_bom_verification(source)

    def child_docs(self, parsed: dict) -> dict[str, list[dict]]:
        return {"materials": parsed["materials"], "storage": parsed["storage"]}

    def label(self, parsed: dict) -> str:
        s = parsed["summary"]
        return f"{s['materials']} materials, {s['passed']} passed, {s['deviations']} BOM deviation(s)"

    def router(self):
        from .router import build_router
        return build_router(self)
