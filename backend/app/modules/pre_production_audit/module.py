"""Pre-Production Audit module - one report per audit of a factory/workshop before production starts.

MongoDB model (every row carries reportId/reportNo/reportDate/spvName/projectName/manufacturer/uploadId):
  ppa_reports  one doc per report: header, audit information (factory, site, type, sequence, benchmark, scope, audit date), conclusion,
               signatories, per-section counts (extra.sections), summary counts   unique: reportNo
  ppa_checks   one doc per readiness check: section, item, requirement, evidence, status (CLOSED/OPEN) and an optional status note
  ppa_nc       one doc per non-conformity: workshop/line, date of finding, description, severity, process, closure status
Every audit report is kept, so the dashboard shows all reports matching the filters.
Media in the Word file is never read, stored or served, and the original .docx is not kept.
"""
from ..base import Column, ParseResult, UploadContext, WidgetDef
from ..simple import SimpleReportModule
from .parser import parse_pre_production_audit


class PreProductionAuditModule(SimpleReportModule):
    key = "pre_production_audit"
    title = "Pre-Production Audit"
    prefix = "ppa"
    children = ("checks", "nc")
    widgets = [
        WidgetDef("kpi_ppa_audits", "Audits", "kpi"),
        WidgetDef("kpi_ppa_checks", "Checks Closed", "kpi"),
        WidgetDef("kpi_ppa_nc", "Non-Conformities", "kpi"),
        WidgetDef("kpi_ppa_open", "Open Non-Conformities", "kpi"),
        WidgetDef("ppa_nc_trend", "Non-Conformities by Date of Finding", "chart"),
        WidgetDef("ppa_audits", "Audits", "table", [
            Column("report_date", "Report Date"), Column("report_no", "Report No"), Column("factory", "Factory"), Column("site", "Site"),
            Column("audit_type", "Audit Type"), Column("sequence", "Sequence"), Column("audit_date", "Audit Date"), Column("checks", "Checks Closed"),
            Column("non_conformities", "Non-Conformities"), Column("conclusion", "Conclusion")]),
        WidgetDef("ppa_sections", "Readiness by Section", "table", [
            Column("report_date", "Report Date"), Column("section", "Section"), Column("checks", "Checks"), Column("closed", "Closed"), Column("open", "Open")]),
        WidgetDef("ppa_checks", "Readiness Checklist", "table", [
            Column("report_date", "Report Date"), Column("section", "Section"), Column("item", "Verification Item"), Column("requirement", "Requirement"),
            Column("evidence", "Evidence / Technical Parameter"), Column("status", "Status"), Column("note", "Note")]),
        WidgetDef("ppa_nonconformities", "Non-Conformities", "table", [
            Column("report_date", "Report Date"), Column("line", "Workshop / Line"), Column("date", "Date of Finding"), Column("description", "Description"),
            Column("severity", "Severity"), Column("process", "Process"), Column("status", "Closure Status"), Column("note", "Note")]),
    ]

    def parse(self, source, ctx: UploadContext) -> ParseResult:
        return parse_pre_production_audit(source)

    def child_docs(self, parsed: dict) -> dict[str, list[dict]]:
        return {"checks": parsed["checks"], "nc": parsed["ncs"]}

    def label(self, parsed: dict) -> str:
        s = parsed["summary"]
        return f"{s['checksClosed']}/{s['checks']} checks closed, {s['ncTotal']} non-conformities ({s['ncOpen']} open), {s['conclusion']}"

    def router(self):
        from .router import build_router
        return build_router(self)
