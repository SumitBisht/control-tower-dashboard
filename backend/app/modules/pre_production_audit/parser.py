"""Parser for the 'Pre-Production Audit Report' Word document.

Same contract as the other parsers: never raises for bad input, ERROR => nothing saved, all problems collected in one pass,
tables recognised by header text, and MEDIA IS NEVER READ (signature images and photos are ignored).
"""
from __future__ import annotations

import re

from docx.table import Table
from docx.text.paragraph import Paragraph

from ..base import Issue, ParseResult
from ..docx_utils import clean, grid, head_text, kv_of, norm_key, open_docx, parse_date, read_header, val

CHECK_HEADS = ("verification item", "equipment station", "checklist item", "stage")
SPLIT_STATUS = re.compile(r"^\s*([A-Za-z ]+?)\s*(?:\((.*)\))?\s*$")


def split_status(raw: str | None) -> tuple[str | None, str | None]:
    """'Closed (First 50MW)' -> ('CLOSED', 'First 50MW'); 'Open' -> ('OPEN', None)."""
    m = SPLIT_STATUS.match(clean(raw))
    if not m or not m.group(1).strip():
        return None, None
    return m.group(1).strip().upper(), (m.group(2) or "").strip() or None


def parse_pre_production_audit(source) -> ParseResult:
    issues: list[Issue] = []
    doc, blocks, error = open_docx(source, "pre production audit report", "Pre-Production Audit")
    if error:
        return ParseResult(None, [error])

    report: dict = {"client": {}}
    audit: dict[str, str] = {}
    conclusion_raw = ""
    signatories: list[dict] = []
    checks: list[dict] = []
    ncs: list[dict] = []
    section = ""
    unreadable = 0
    for b in blocks:
        if isinstance(b, Paragraph):
            t = clean(b.text)
            if t:
                section = t
            continue
        try:
            g = grid(b)
        except Exception:  # noqa: BLE001
            unreadable += 1
            continue
        if not g or not g[0]:
            continue
        head = head_text(g, 1)
        first = norm_key(g[0][0])
        last = norm_key(g[0][-1])
        if first.startswith("audit conclusion") and len(g) > 1:
            conclusion_raw = clean(g[1][0])
        elif first in ("prepared by", "reviewed by", "approved by"):
            signatories += [{"role": clean(r[0]), "title": clean(r[1]) if len(r) > 1 else ""} for r in g if r and clean(r[0])]
        elif "workshop line" in head and "date of finding" in head and "closure status" in head:
            for r in g[1:]:
                if len(r) < 6 or not clean(r[2]):
                    continue
                status, note = split_status(r[5])
                ncs.append({"line": val(r[0]), "date": parse_date(r[1]), "dateRaw": clean(r[1]), "description": clean(r[2]), "severity": (val(r[3]) or "").title() or None,
                            "process": val(r[4]), "status": status, "statusNote": note})
        elif last == "status" and any(head.startswith(h) for h in CHECK_HEADS) and len(g[0]) >= 4:
            for r in g[1:]:
                if len(r) < 4 or not clean(r[0]):
                    continue
                status, note = split_status(r[-1])
                checks.append({"section": section, "item": clean(r[0]), "requirement": val(r[1]), "evidence": val(r[2]), "status": status, "statusNote": note})
        else:
            kv = kv_of(b)
            if "audit type" in kv or "factory" in kv or "site" in kv:
                audit.update({k: v for k, v in kv.items() if v})
    if unreadable:
        issues.append(Issue("WARNING", "TABLES_SKIPPED", f"{unreadable} table(s) could not be read and were skipped."))
    read_header(blocks, issues, report)
    if not checks:
        issues.append(Issue("ERROR", "CHECKS_MISSING", "No audit checklist tables (Verification Item / Readiness Check / Status) were found."))
    if any(i.level == "ERROR" for i in issues):
        return ParseResult(None, issues)
    if not audit:
        issues.append(Issue("WARNING", "AUDIT_INFO_MISSING", "The 'Audited Organization' / 'Audit Information' tables were not found."))
    if not conclusion_raw:
        issues.append(Issue("WARNING", "CONCLUSION_MISSING", "The 'Audit Conclusion' is missing; it will be derived from the checklist status."))
    if not ncs:
        issues.append(Issue("WARNING", "NC_TABLE_MISSING", "The 'Summary of Non-Conformities' table was not found or is empty."))

    for c in checks:
        if c["status"] not in ("CLOSED", "OPEN"):
            issues.append(Issue("WARNING", "STATUS_UNKNOWN", f"Check '{c['item']}' ({c['section']}): status '{c['status']}' is neither Closed nor Open."))
    for n in ncs:
        if n["date"] is None:
            issues.append(Issue("WARNING", "NC_DATE_INVALID", f"Non-conformity '{n['description'][:50]}': date '{n['dateRaw']}' is not a valid date."))
        if n["status"] not in ("CLOSED", "OPEN"):
            issues.append(Issue("WARNING", "NC_STATUS_UNKNOWN", f"Non-conformity '{n['description'][:50]}': closure status '{n['status']}' is neither Closed nor Open."))

    open_checks = sum(1 for c in checks if c["status"] != "CLOSED")
    open_ncs = sum(1 for n in ncs if n["status"] != "CLOSED")
    conclusion = clean(conclusion_raw).upper() or ("READY" if not open_checks and not open_ncs else "NOT READY")
    if norm_key(conclusion) == "ready" and (open_checks or open_ncs):
        issues.append(Issue("WARNING", "CONCLUSION_CONFLICT", f"The audit conclusion is READY but {open_checks} check(s) and {open_ncs} non-conformity(ies) are not closed."))

    sections: dict[str, dict] = {}
    for c in checks:
        s = sections.setdefault(c["section"], {"checks": 0, "closed": 0})
        s["checks"] += 1
        s["closed"] += c["status"] == "CLOSED"
    summary = {
        "checks": len(checks), "checksClosed": len(checks) - open_checks, "checksOpen": open_checks,
        "checksConditional": sum(1 for c in checks if c["status"] == "CLOSED" and c["statusNote"]),
        "ncTotal": len(ncs), "ncMajor": sum(1 for n in ncs if n["severity"] == "Major"), "ncMinor": sum(1 for n in ncs if n["severity"] == "Minor"),
        "ncOpen": open_ncs, "ncClosed": len(ncs) - open_ncs, "conclusion": conclusion, "sections": len(sections),
    }
    report["conclusion"] = conclusion
    report["audit"] = {"factory": audit.get("factory"), "site": audit.get("site"), "address": audit.get("address"), "type": audit.get("audit type"),
                       "sequence": audit.get("sequence"), "benchmark": audit.get("benchmark"), "scope": audit.get("scope"), "auditDate": audit.get("audit date")}
    report["signatories"] = signatories
    issues.insert(0, Issue("INFO", "PARSED", f"Parsed report {report['reportNo']}: {len(checks)} checks in {len(sections)} sections "
                           f"({summary['checksClosed']} closed), {len(ncs)} non-conformities ({open_ncs} open), conclusion {conclusion}. Media in the document was ignored."))
    return ParseResult({"report": report, "checks": checks, "ncs": ncs, "extra": {"sections": sections}, "summary": summary}, issues)
