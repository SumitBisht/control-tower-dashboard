"""Parser for the 'DSR Pre-Shipment Inspection (PSI) Report' Word document (one report per lot).

Same contract as the other parsers: never raises for bad input, ERROR => nothing saved, all problems collected in one pass,
tables recognised by header text, and MEDIA IS NEVER READ (photographic-record tables and embedded images are ignored).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..base import Issue, ParseResult
from ..docx_utils import (clean, grid, head_text, intval, is_blank, iter_blocks, kv_of, norm_key, num, parse_date, records,
                          result_of, val, row_cells)

TEST_NAMES = [  # heading keyword -> canonical test name
    ("maximum power", "Maximum Power Determination"), ("el image", "EL Test"), ("visual", "Visual Check"), ("dimension", "Dimension Inspection"),
    ("insulation", "Insulation Test"), ("wet leakage", "Wet Leakage Test"), ("bi faciality", "Bi-Faciality Factor"),
    ("static mechanical", "Static Mechanical Load Test"), ("dynamic mechanical", "Cyclic (Dynamic) Mechanical Load Test"),
    ("robustness", "Robustness of Terminations Test"), ("low irradiance", "Low Irradiance Test"),
]
HEADING_RX = re.compile(r"^\s*tests?\s+evaluation\s*[-–—]\s*(.+?)\s*$", re.I)
TIME_RX = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*/?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?")


def canonical_test(heading: str) -> str:
    h = norm_key(heading)
    for key, name in TEST_NAMES:
        if key in h:
            return name
    return clean(heading)


def parse_time(s: str) -> datetime | None:
    m = TIME_RX.search(s or "")
    if m:
        d, mo, y, hh, mm, ss = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss or 0))
        except ValueError:
            return None
    return parse_date(s or "")


def classify(g: list[list[str]], table: Table) -> str | None:
    if not g or not g[0]:
        return None
    head = head_text(g)
    first = norm_key(g[0][0])
    if "watt class" in head and "total modules" in head:
        return "output"
    if "inspection test" in head and "testing standard" in head and "aql" in head:
        return "result_summary"
    if "applicable inspection" in head and "equipment manufacturer" in head:
        return "test_conditions"
    if "test performance" in head and "sun simulator equipment" in head:
        return "calibration"
    if "non conformity category" in head and "risk category" in head:
        return "nc_results"
    if "pre pdi" in head and "during pdi" in head:
        return "max_power"
    if "defect description" in head and "acceptance limit" in head:
        return "nc_summary"
    if "module serial no" in head and "defect representation" in head:
        return "nc_modules"
    if "dcw" in head and "gnd" in head:
        return "insulation"
    if "applied voltage" in head and "test time" in head:
        return "wet_leakage"
    if "back side electrical data" in head:
        return "bifaciality"
    if "before test" in head and "after test" in head:
        return "mech_load"
    if "1000 w m" in head and "200 w m" in head:
        return "low_irradiance"
    if first == "inspection conclusion":
        return "conclusion"
    if first in ("prepared by", "reviewed by", "approved by"):
        return "signatories"
    kv = kv_of(table)
    if "lot number" in kv and "report number" in kv:
        return "general"
    return None


def parse_output(g) -> tuple[list[dict], dict | None]:
    rows, total = [], None
    for r in g[1:]:
        if len(r) < 4 or not any(r):
            continue
        item = {"wattClass": intval(r[0]), "modules": intval(r[1]), "mwp": num(r[2]), "productType": val(r[3]), "remarks": val(r[4]) if len(r) > 4 else None}
        if norm_key(r[0]).startswith("total"):
            total = item
        elif item["wattClass"] is not None:
            rows.append(item)
    return rows, total


def parse_result_summary(g) -> list[dict]:
    out = []
    for r in g[1:]:
        if len(r) < 7 or not clean(r[0]):
            continue
        out.append({"test": r[0], "standard": val(r[1]), "aql": val(r[2]), "sampling": intval(r[3]), "observation": val(r[4]),
                    "decision": result_of(r[5]), "remarks": val(r[6])})
    return out


def parse_test_conditions(g) -> list[dict]:
    out = []
    for r in g[1:]:
        if len(r) < 10 or not clean(r[0]):
            continue
        out.append({"test": r[0], "applicable": val(r[1]), "process": val(r[2]), "manufacturer": val(r[3]), "model": val(r[4]), "serialNo": val(r[5]),
                    "lastCalibration": parse_date(r[6]), "nextCalibration": parse_date(r[7]), "observation": val(r[8]), "evaluation": result_of(r[9])})
    return out


def parse_calibration(g) -> list[dict]:
    rows, _ = records(g, 1)
    out = []
    for r in rows:
        r["test_time"] = parse_time(r.get("test_time") or "") or r.get("test_time")
        out.append(r)
    return out


def parse_nc_results(g) -> list[dict]:
    out = []
    for r in g[1:]:
        if len(r) < 5 or not clean(r[0]):
            continue
        cat, desc = val(r[1]), val(r[2])
        count = intval(r[4])
        if (norm_key(cat or "") in ("", "n a")) and (norm_key(desc or "") in ("", "n a")) and not count:
            continue
        out.append({"test": r[0], "category": cat, "description": desc, "risk": val(r[3]), "count": count or 0})
    return out


def parse_max_power(g) -> dict[str, Any]:
    rows, stats = [], {}
    cols = ["pmax", "vpm", "ipm", "ff", "pmax1", "vpm1", "ipm1", "ff1", "diffWp", "diffPct"]
    for r in g[2:]:
        if len(r) < 12 or not any(r):
            continue
        label = norm_key(r[0])
        vals = {c: num(r[2 + i].replace("%", "")) for i, c in enumerate(cols)}
        if re.fullmatch(r"\d+", r[0].strip().rstrip(".")):
            rows.append({"srNo": intval(r[0]), "moduleNo": val(r[1]), **vals, "dimension": val(r[12]) if len(r) > 12 else None})
        elif label in ("minimum", "maximum", "average"):
            stats[label] = vals
    diffs = [x["diffPct"] for x in rows if x["diffPct"] is not None]
    return {"rows": rows, "stats": stats,
            "summary": {"modules": len(rows), "outOfTolerance": sum(1 for d in diffs if abs(d) > 1.0),
                        "avgPre": round(sum(x["pmax"] for x in rows if x["pmax"] is not None) / len(rows), 2) if rows else None,
                        "avgDuring": round(sum(x["pmax1"] for x in rows if x["pmax1"] is not None) / len(rows), 2) if rows else None,
                        "avgDiffPct": round(sum(diffs) / len(diffs), 3) if diffs else None, "maxAbsDiffPct": round(max(abs(d) for d in diffs), 3) if diffs else None}}


def parse_nc_summary(g) -> list[dict]:
    out = []
    for r in g[2:]:
        if len(r) < 6 or not clean(r[0]):
            continue
        out.append({"defect": val(r[0]), "limitMajor": intval(r[1]), "limitMinor": intval(r[2]), "observedMajor": intval(r[3]),
                    "observedMinor": intval(r[4]), "evaluation": result_of(r[5])})
    return out


def parse_nc_modules(g) -> list[dict]:
    out = []
    for r in g[1:]:
        if len(r) < 3:
            continue
        serial, defect = val(r[1]), val(r[2])
        if norm_key(serial or "") in ("", "n a") and norm_key(defect or "") in ("", "n a"):
            continue
        out.append({"srNo": intval(r[0]), "serialNo": serial, "defect": defect})
    return out


def parse_typed_rows(g, header_rows: int, cols: list[str], numeric: set[str]) -> list[dict]:
    def conv(c: str, x: str):
        if c == "srNo":
            return intval(x)
        return num(x.replace("%", "")) if c in numeric else val(x)
    return [{c: conv(c, r[i]) for i, c in enumerate(cols)}
            for r in g[header_rows:] if len(r) >= len(cols) and clean(r[1])]


# ------------------------------------------------------------------ main entry
def parse_pre_shipment(source) -> ParseResult:
    issues: list[Issue] = []

    def err(code, msg, **ctx):
        issues.append(Issue("ERROR", code, msg, ctx))

    def warn(code, msg, **ctx):
        issues.append(Issue("WARNING", code, msg, ctx))

    src = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source)
    if not zipfile.is_zipfile(src):
        err("NOT_DOCX", "The file is not a valid .docx document (legacy .doc, corrupted, or renamed file).")
        return ParseResult(None, issues)
    if isinstance(src, io.BytesIO):
        src.seek(0)
    try:
        doc = Document(src)
    except Exception as e:  # noqa: BLE001
        err("DOCX_UNREADABLE", f"The Word document could not be opened: {type(e).__name__}.")
        return ParseResult(None, issues)

    blocks = list(iter_blocks(doc))
    titles = [norm_key(b.text) for b in blocks[:40] if isinstance(b, Paragraph)]
    if "pre shipment inspection report" not in titles:
        err("WRONG_REPORT_TYPE", "This does not look like a Pre-Shipment Inspection report (title 'PRE-SHIPMENT INSPECTION REPORT' not found). "
            "Check you selected the right module for this file.")
        return ParseResult(None, issues)

    report: dict[str, Any] = {"client": {}, "signatories": []}
    kv_info: dict[str, str] = {}
    general: dict[str, str] = {}
    watt_rows: list[dict] = []
    watt_total: dict | None = None
    conclusion_raw = ""
    results: list[dict] = []
    conditions: list[dict] = []
    calibration: list[dict] = []
    nc_results: list[dict] = []
    max_power: dict | None = None
    nc_summary: dict[str, list[dict]] = {}
    nc_modules: dict[str, list[dict]] = {}
    tests: dict[str, list[dict]] = {"insulation": [], "wetLeakage": [], "biFaciality": [], "dynamicLoad": [], "staticLoad": [], "robustness": [], "lowIrradiance": []}
    ctx_test: str | None = None
    unreadable = 0

    for b in blocks:
        if isinstance(b, Paragraph):
            m = HEADING_RX.match(clean(b.text))
            if m:
                ctx_test = canonical_test(m.group(1))
            continue
        try:
            g = grid(b)
            kind = classify(g, b)
        except Exception:  # noqa: BLE001
            unreadable += 1
            continue
        if kind is None:
            kv = kv_of(b)
            if "report no" in kv:
                kv_info = kv
            if "spv name" in kv or "project name" in kv:
                report["client"] = {"name": kv.get("client", "")}
                report["spvName"], report["projectName"] = kv.get("spv name", ""), kv.get("project name", "")
            continue
        if kind == "general":
            general = kv_of(b)
        elif kind == "output":
            watt_rows, watt_total = parse_output(g)
        elif kind == "conclusion":
            conclusion_raw = clean(g[1][0]) if len(g) > 1 and g[1] else ""
        elif kind == "signatories":
            report["signatories"] += [{"role": r[0], "designation": r[1] if len(r) > 1 else "", "name": ""} for r in g]
        elif kind == "result_summary":
            results += parse_result_summary(g)
        elif kind == "test_conditions":
            conditions += parse_test_conditions(g)
        elif kind == "calibration":
            calibration += parse_calibration(g)
        elif kind == "nc_results":
            nc_results += parse_nc_results(g)
        elif kind == "max_power":
            mp = parse_max_power(g)
            if max_power is None:
                max_power = mp
            else:
                max_power["rows"] += mp["rows"]
        elif kind == "nc_summary":
            nc_summary.setdefault(ctx_test or "Unknown", []).extend(parse_nc_summary(g))
        elif kind == "nc_modules":
            nc_modules.setdefault(ctx_test or "Unknown", []).extend(parse_nc_modules(g))
        elif kind == "insulation":
            tests["insulation"] += records(g, 1)[0]
        elif kind == "wet_leakage":
            tests["wetLeakage"] += records(g, 1)[0]
        elif kind == "bifaciality":
            tests["biFaciality"] += parse_typed_rows(g, 2, ["srNo", "moduleNo", "moduleType", "frontPmax", "frontVpm", "frontIpm", "frontFf", "backPmax",
                                                           "backVpm", "backIpm", "backFf", "biFacialityPct"],
                                                     {"frontPmax", "frontVpm", "frontIpm", "frontFf", "backPmax", "backVpm", "backIpm", "backFf", "biFacialityPct"})
        elif kind == "low_irradiance":
            tests["lowIrradiance"] += parse_typed_rows(g, 2, ["srNo", "moduleNo", "moduleType", "pmax", "vpm", "ipm", "ff", "pmax200", "vpm200", "ipm200",
                                                             "ff200", "ratioPct"],
                                                       {"pmax", "vpm", "ipm", "ff", "pmax200", "vpm200", "ipm200", "ff200", "ratioPct"})
        elif kind == "mech_load":
            name = norm_key(ctx_test or "")
            key = "dynamicLoad" if "dynamic" in name or "cyclic" in name else "staticLoad" if "static" in name else "robustness"
            tests[key] += records(g, 1)[0]
    if unreadable:
        warn("TABLES_SKIPPED", f"{unreadable} table(s) could not be read and were skipped.")

    # ---- header
    if not kv_info:
        err("REPORT_INFO_MISSING", "The 'Report No. / Report Date / Manufacturer / Location / Workshop' table was not found.")
        return ParseResult(None, issues)
    report_no = kv_info.get("report no", "")
    if is_blank(report_no):
        err("REPORT_NO_MISSING", "Report No. is empty or still a placeholder ('xxxxx'). Fill it in before uploading.")
    rd = parse_date(kv_info.get("report date", ""))
    if not rd:
        err("REPORT_DATE_INVALID", f"Report Date '{kv_info.get('report date', '')}' is not a valid date (expected e.g. 04.10.2026).")
    for k, label in (("manufacturer", "Manufacturer"), ("location", "Location"), ("workshop", "Workshop")):
        v = kv_info.get(k, "")
        if is_blank(v):
            warn("HEADER_FIELD_BLANK", f"{label} is blank or a placeholder.")
            v = "Unknown" if k == "manufacturer" else ""
        report[k] = v
    report.update(reportNo=report_no, reportDate=rd)
    if not report.get("spvName"):
        warn("SPV_MISSING", "SPV name not found in the document; set it on the upload form.")
    if not report.get("projectName"):
        warn("PROJECT_MISSING", "Project name not found in the document; set it on the upload form.")

    # ---- lot information
    lot_no = (general.get("lot number") or "").strip()
    if not general:
        err("GENERAL_INFO_MISSING", "The 'General Information' table (Report Number / Factory / Lot Number / Lot Size) was not found.")
    elif is_blank(lot_no):
        err("LOT_NUMBER_MISSING", "Lot Number is empty or a placeholder in the General Information table.")
    if not results:
        err("RESULT_SUMMARY_MISSING", "The 'Result Summary' table (Inspection/Test, Standard, AQL, Sampling, Observation, Decision) was not found.")
    if any(i.level == "ERROR" for i in issues):
        return ParseResult(None, issues)

    lot = {"lotNo": lot_no, "factory": val(general.get("factory")),
           "sizePcs": intval(general.get("lot size in pcs")), "sizeMwp": num(general.get("lot size in mwp"))}
    if not watt_rows:
        warn("OUTPUT_SUMMARY_MISSING", "'Output Summary based on Power Wattage' table not found.")
    else:  # cross-check lot size against watt classes and capacity
        pcs = sum(r["modules"] or 0 for r in watt_rows)
        if lot["sizePcs"] is not None and pcs != lot["sizePcs"]:
            warn("LOT_SIZE_MISMATCH", f"Lot size says {lot['sizePcs']:,} pcs but the output summary adds up to {pcs:,}.")
        mwp = sum((r["modules"] or 0) * (r["wattClass"] or 0) for r in watt_rows) / 1e6
        if lot["sizeMwp"] and abs(mwp - lot["sizeMwp"]) > 0.005 * lot["sizeMwp"]:
            warn("LOT_MWP_MISMATCH", f"Lot size says {lot['sizeMwp']} MWp but the modules x watt class give {mwp:.4f} MWp.")
    if max_power is None:
        warn("MAX_POWER_MISSING", "'Maximum Power Determination' table not found.")
    conclusion = {"pass": "PASS", "fail": "FAIL"}.get(norm_key(conclusion_raw))
    if conclusion is None:
        warn("CONCLUSION_UNSET", "Inspection conclusion is not exactly 'Pass' or 'Fail'; it will be derived from the test decisions.")
    decisions = [r["decision"] for r in results]
    if conclusion is None:
        conclusion = "FAIL" if "FAIL" in decisions else "PASS" if "PASS" in decisions else None
    elif conclusion == "PASS" and "FAIL" in decisions:
        warn("CONCLUSION_CONFLICT", "Report conclusion is PASS but at least one test decision is FAIL.")
    for r in results:
        if r["decision"] is None:
            warn("DECISION_UNKNOWN", f"Test '{r['test']}': decision is not PASS/FAIL.")
        need = re.search(r"(\d+)\s*nos?\.?\s*/\s*(?:lot|psi)", r["aql"] or "", re.I)
        if need and r["sampling"] is not None and r["sampling"] < int(need.group(1)):
            warn("SAMPLING_BELOW_PLAN", f"Test '{r['test']}': sampling is {r['sampling']} but the plan ('{r['aql']}') requires {need.group(1)}.")

    # ---- expired equipment calibration (relative to the report date)
    overdue = [c for c in conditions if c["nextCalibration"] and rd and c["nextCalibration"] < rd]
    for c in overdue:
        warn("CALIBRATION_OVERDUE", f"Equipment for '{c['test']}' ({c['serialNo']}) was due for calibration on {c['nextCalibration']:%d-%m-%Y}, before the report date.")

    nc_total = sum(n["count"] for n in nc_results)
    summary = {
        "lotNo": lot_no, "lotSizePcs": lot["sizePcs"], "lotSizeMwp": lot["sizeMwp"], "tests": len(results),
        "testsPassed": sum(1 for d in decisions if d == "PASS"), "testsFailed": sum(1 for d in decisions if d == "FAIL"),
        "ncTotal": nc_total, "ncMajor": sum(n["count"] for n in nc_results if norm_key(n.get("risk") or n.get("category") or "") == "major"),
        "ncMinor": sum(n["count"] for n in nc_results if norm_key(n.get("risk") or n.get("category") or "") == "minor"),
        "equipmentOverdue": len(overdue), "powerOutOfTolerance": (max_power or {}).get("summary", {}).get("outOfTolerance"),
        "avgDiffPct": (max_power or {}).get("summary", {}).get("avgDiffPct"), "conclusion": conclusion,
    }
    data = {"report": report, "lot": lot, "wattClasses": watt_rows, "wattTotal": watt_total, "conclusion": conclusion, "results": results,
            "ncs": nc_results, "summary": summary,
            "details": {"testConditions": conditions, "calibration": calibration, "maxPower": max_power, "ncSummary": nc_summary,
                        "ncModules": nc_modules, **tests}}
    issues.insert(0, Issue("INFO", "PARSED", f"Parsed report {report_no}: lot {lot_no}, {lot['sizePcs']:,} modules, {len(results)} tests "
                           f"({summary['testsPassed']} pass / {summary['testsFailed']} fail), {nc_total} non-conformit{'y' if nc_total == 1 else 'ies'}. "
                           "Media in the document was ignored."))
    return ParseResult(data, issues)
