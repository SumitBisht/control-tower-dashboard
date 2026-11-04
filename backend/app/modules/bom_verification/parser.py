"""Parser for the 'BOM Verification Report (Store)' Word document.

Same contract as the other parsers: never raises for bad input, ERROR => nothing saved, all problems collected in one pass,
tables recognised by header text, and MEDIA IS NEVER READ (the picture tables are ignored).
"""
from __future__ import annotations

from difflib import SequenceMatcher

from docx.table import Table

from ..base import Issue, ParseResult
from ..docx_utils import alnum, clean, grid, head_text, num, open_docx, read_header, result_of, val


def classify(g: list[list[str]]) -> str | None:
    if not g or not g[0]:
        return None
    head = head_text(g)
    if "material name" in head and "as per bom" in head and "as per actual" in head:
        return "materials"
    if "temperature" in head and "humidity" in head and "expiry date" in head:
        return "storage"
    return None


def same(a: str | None, b: str | None) -> bool:
    """Equal ignoring case, punctuation and small typos ('m²' vs 'm²²'); a different supplier/model/country is far below the threshold."""
    x, y = alnum(a or ""), alnum(b or "")
    return x == y or SequenceMatcher(None, x, y).ratio() >= 0.95


def nil(x: str | None) -> str | None:
    v = val(x)
    return None if v and v.lower() == "nil" else v


def parse_bom_verification(source) -> ParseResult:
    issues: list[Issue] = []
    doc, blocks, error = open_docx(source, "bom verification report", "BOM Verification")
    if error:
        return ParseResult(None, [error])

    report: dict = {"client": {}}
    materials: list[dict] = []
    storage: list[dict] = []
    unreadable = 0
    for b in blocks:
        if not isinstance(b, Table):
            continue
        try:
            g = grid(b)
            kind = classify(g)
        except Exception:  # noqa: BLE001
            unreadable += 1
            continue
        if kind == "materials" and not materials:
            for r in g[2:]:
                if len(r) < 8 or not clean(r[0]):
                    continue
                materials.append({"material": clean(r[0]), "bomMake": val(r[1]), "actualMake": val(r[2]), "bomOrigin": val(r[3]), "actualOrigin": val(r[4]),
                                  "batchNo": val(r[5]), "result": result_of(r[6]), "remarks": nil(r[7])})
        elif kind == "storage" and not storage:
            for r in g[1:]:
                if len(r) < 7 or not clean(r[0]):
                    continue
                storage.append({"material": clean(r[0]), "temperatureC": num(r[1]), "humidityPct": num(r[2]), "expiry": nil(r[3]),
                                "observation": nil(r[4]), "result": result_of(r[5]), "remarks": nil(r[6])})
    if unreadable:
        issues.append(Issue("WARNING", "TABLES_SKIPPED", f"{unreadable} table(s) could not be read and were skipped."))
    read_header(blocks, issues, report)
    if not materials:
        issues.append(Issue("ERROR", "MATERIALS_MISSING", "The 'List of Materials Available' table (Material Name, As per BOM / As per Actual, Batch No., Results) was not found or is empty."))
    if any(i.level == "ERROR" for i in issues):
        return ParseResult(None, issues)
    if not storage:
        issues.append(Issue("WARNING", "STORAGE_MISSING", "The 'Materials Storage Conditions' table was not found."))

    for m in materials:
        m["makeMatch"] = same(m["bomMake"], m["actualMake"])
        m["originMatch"] = same(m["bomOrigin"], m["actualOrigin"])
        m["deviation"] = not (m["makeMatch"] and m["originMatch"])
        if m["result"] is None:
            issues.append(Issue("WARNING", "RESULT_MISSING", f"Material '{m['material']}': Result is blank."))
        if m["deviation"]:
            what = " and ".join(x for x, ok in (("make/model", m["makeMatch"]), ("country of origin", m["originMatch"])) if not ok)
            issues.append(Issue("WARNING", "BOM_DEVIATION", f"Material '{m['material']}': {what} differs between the BOM and the actual material."))
            if m["result"] == "PASS":
                issues.append(Issue("WARNING", "PASS_WITH_DEVIATION", f"Material '{m['material']}' is marked Pass although it deviates from the BOM."))
        if not m["batchNo"]:
            issues.append(Issue("WARNING", "BATCH_MISSING", f"Material '{m['material']}': Batch No. is blank."))
    for s in storage:
        if s["temperatureC"] is None or s["humidityPct"] is None:
            issues.append(Issue("WARNING", "STORAGE_READING_MISSING", f"Storage of '{s['material']}': temperature or humidity is not a number."))

    def avg(key):
        xs = [s[key] for s in storage if s[key] is not None]
        return round(sum(xs) / len(xs), 1) if xs else None

    summary = {
        "materials": len(materials), "passed": sum(1 for m in materials if m["result"] == "PASS"),
        "failed": sum(1 for m in materials if m["result"] == "FAIL"),
        "underReview": sum(1 for m in materials if m["result"] not in ("PASS", "FAIL")),
        "deviations": sum(1 for m in materials if m["deviation"]),
        "storageItems": len(storage), "storagePassed": sum(1 for s in storage if s["result"] == "PASS"),
        "storageIssues": sum(1 for s in storage if s["result"] != "PASS"), "avgTempC": avg("temperatureC"), "avgHumidityPct": avg("humidityPct"),
    }
    issues.insert(0, Issue("INFO", "PARSED", f"Parsed report {report['reportNo']}: {len(materials)} materials ({summary['passed']} pass), "
                           f"{len(storage)} storage readings. Media in the document was ignored."))
    return ParseResult({"report": report, "materials": materials, "storage": storage, "summary": summary}, issues)
