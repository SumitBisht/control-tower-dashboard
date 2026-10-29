"""Parser for the 'DSR Report - Production Supervision' Word document.

Rules (same graceful-termination contract as the container parser):
  * parse() never raises for bad input; every problem becomes an Issue. ERROR => nothing is saved.
  * Tables are recognised by their header text, not by position, so optional sections / extra lines / extra days are fine.
  * MEDIA IS NEVER READ: picture tables, embedded images and videos are ignored (no blobs are extracted or stored).
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from datetime import datetime
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..base import Issue, ParseResult
from ..docx_utils import (clean, grid, head_text, intval, is_blank, iter_blocks, kv_of, norm_key, num, parse_date, records,  # noqa: F401
                          result_of, snake, val, alnum, parse_float, parse_int, row_cells, strip_colon)

SECTION_RX = re.compile(r"^\s*lines?\s*[-–—]?\s*(\d[\d\s&,/]*?)\s*[-–—]\s*(day|night)\s*shift\s*$", re.I)


def classify(g: list[list[str]], table: Table) -> str | None:
    if not g or not g[0]:
        return None
    head = head_text(g)
    first = norm_key(g[0][0])
    if "power bin" in head and "planned output" in head:
        return "production"
    if "module ytd" in head and "rejected" in head:
        return "qualification"
    if "ipqc process" in head:
        return "ipqc"
    if "material name" in head and "as per bom" in head:
        return "bom"
    if "temperature" in head and "humidity" in head and "expiry date" in head:
        return "storage"
    if "date of finding" in head and "no of affected modules" in head:
        return "nc_summary"
    if "date of finding" in head and "rejected module sr no" in head:
        return "nc_cumulative"
    if "equipment make" in head and "lamp usage" in head:
        return "flasher_verification"
    if "flash date" in head:
        return "flasher_results"
    if "front soldering test" in head:
        return "soldering"
    if "gel content" in head and "laminator no" in head:
        return "gel"
    if "length mm" in head and "module serial number" in head:
        return "dimension"
    if "module sr no" in head and "pmax" in head:
        return "rfid"
    if "item property measured" in head:
        return "internal_lab"
    if "storage area" in head and "product stored" in head:
        return "finished_storage"
    if "date of production" in head and "data collected" in head:
        return "data_verification"
    if first == "description" and "values" in head:
        return "calibration_basic"
    if first == "reference module" and "1st reference" in head:
        return "calibration_reference"
    if "reference module serial number" in head and "fill factor" in head:
        return "first_measurement"
    if first in ("prepared by", "reviewed by", "approved by"):
        return "signatories"
    kv = kv_of(table)
    if "finding date" in kv and "non conformity description" in kv:
        return "nc_record"
    return None


# ------------------------------------------------------------------ typed table parsers
def _units(row0: list[str], row1: list[str], start: int) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for j in range(start, len(row0)):
        u = norm_key(row1[j]) if j < len(row1) else ""
        unit = "pcs" if "pcs" in u else "mwp" if "mwp" in u else None
        if unit:
            groups.setdefault(norm_key(row0[j]), {})[unit] = j
    return groups


def _qm(r: list[str], cols: dict[str, int] | None) -> dict[str, Any] | None:
    if not cols:
        return None
    return {"qty": intval(r[cols["pcs"]]) if "pcs" in cols and cols["pcs"] < len(r) else None,
            "mwp": num(r[cols["mwp"]]) if "mwp" in cols and cols["mwp"] < len(r) else None}


def parse_production(g, warn) -> tuple[list[dict], dict | None]:
    if len(g) < 3:
        return [], None
    groups = _units(g[0], g[1], 2)
    want = {"planned": "planned output", "actual": "actual output", "deviation": "deviation", "day": "day shift", "night": "night shift"}
    missing = [k for k, name in want.items() if name not in groups]
    if missing:
        warn("PRODUCTION_COLUMNS", f"Production snapshot is missing column group(s): {', '.join(missing)}.")
    rows, total = [], None
    for r in g[2:]:
        if not any(r):
            continue
        entry = {k: _qm(r, groups.get(name)) for k, name in want.items()}
        d = parse_date(r[0])
        if d:
            m = re.search(r"\d+", r[1] if len(r) > 1 else "")
            rows.append({"date": d, "powerBin": int(m.group()) if m else None, **entry})
        elif norm_key(r[0]).startswith("total"):
            total = entry
    return rows, total


def parse_qualification(g, warn) -> list[dict]:
    if len(g) < 3:
        return []
    groups = _units(g[0], g[1], 1)
    out = []
    for r in g[2:]:
        if not any(r):
            continue
        d = parse_date(r[0])
        cumulative = norm_key(r[0]).startswith("cumulative")
        if not d and not cumulative:
            continue
        row: dict[str, Any] = {"kind": "cumulative" if cumulative else "daily", "date": d, "qualified": {}}
        for name, cols in groups.items():
            m = re.match(r"(\d+)\s*wp\s*qualified", name)
            if m:
                row["qualified"][m.group(1)] = _qm(r, cols)
            elif name == "module ytd":
                row["moduleYtd"] = _qm(r, cols)
            elif name == "rejected":
                row["rejected"] = _qm(r, cols)
            elif name.startswith("el rework"):
                row["elReworkRejected"] = _qm(r, cols)
            elif name.startswith("suspected"):
                row["suspected"] = _qm(r, cols)
        out.append(row)
    return out


def parse_bom(g, line: str | None, shift: str | None) -> list[dict]:
    out = []
    for r in g[2:]:
        if not r or not clean(r[0]) or len(r) < 8:
            continue
        make_bom, make_act, org_bom, org_act = r[1], r[2], r[3], r[4]
        out.append({"material": r[0], "makeBom": make_bom, "makeActual": make_act, "originBom": org_bom, "originActual": org_act,
                    "batchNo": val(r[5]), "result": result_of(r[6]), "remarks": val(r[7]),
                    # None = actual not recorded (e.g. warehouse closed on night shift): not a deviation
                    "makeMatches": (alnum(make_bom) == alnum(make_act)) if alnum(make_act) else None,
                    "originMatches": (alnum(org_bom) == alnum(org_act)) if alnum(org_act) else None})
    return out


def parse_storage(g) -> list[dict]:
    return [{"material": r[0], "temperatureC": num(r[1]), "humidityPct": num(r[2]), "expiry": val(r[3]), "observations": val(r[4]),
             "result": result_of(r[5]), "remarks": val(r[6])} for r in g[1:] if len(r) >= 7 and clean(r[0])]


def parse_ipqc(g) -> list[dict]:
    hdr = [norm_key(c) for c in g[0]]

    def col(sub):
        return next((j for j, h in enumerate(hdr) if sub in h), None)
    idx = {"process": col("process"), "ipqc": col("ipqc process"), "params": col("equipment settings"), "qty": col("qty"),
           "test": col("test results"), "insp": col("inspection results"), "line": col("workshop"), "remarks": col("remarks")}
    # "process" matches the first column (header "Process"); "ipqc process" is a different, later column
    idx["process"] = 0

    def at(r, k):
        j = idx[k]
        return r[j] if j is not None and j < len(r) else ""
    out = []
    for r in g[1:]:
        if not clean(at(r, "ipqc")):
            continue
        out.append({"process": val(at(r, "process")), "check": val(at(r, "ipqc")), "parameters": val(at(r, "params")),
                    "qtyTested": val(at(r, "qty")), "testResult": val(at(r, "test")), "result": result_of(at(r, "insp")),
                    "line": val(at(r, "line")), "remarks": val(at(r, "remarks"))})
    return out


def parse_soldering(g) -> list[dict]:
    row0 = [norm_key(c) for c in g[0]]
    front = [j for j, h in enumerate(row0) if h.startswith("front")]
    rear = [j for j, h in enumerate(row0) if h.startswith("rear")]
    out = []
    for r in g[2:]:
        d = parse_date(r[2]) if len(r) > 2 else None
        if not d:
            continue
        out.append({"line": val(r[0]), "shift": val(r[1]), "date": d,
                    "front": [num(r[j]) for j in front if j < len(r)], "rear": [num(r[j]) for j in rear if j < len(r)]})
    return out


def parse_nc_record(table: Table) -> dict | None:
    kv = kv_of(table)

    def g(prefix):
        return next((val(v) for k, v in kv.items() if k.startswith(prefix)), None)
    desc = g("non conformity description")
    if not desc:
        return None
    return {"date": parse_date(g("finding date") or ""), "description": desc, "shift": g("production shift"),
            "additionalDetails": g("additional details"), "affectedModules": intval(g("number of affected")),
            "severity": g("severity"), "closedImmediately": g("non conformity closed"), "process": g("manufacturing process"),
            "vendorAction": g("immediate action"), "closureStatus": g("closure status")}


def nc_status(closure: str | None) -> str:
    v = norm_key(closure or "")
    if re.search(r"open|pending|progress", v):
        return "OPEN"
    return "CLOSED" if "closed" in v else "UNKNOWN"


def nc_from_table(g, cumulative: bool) -> list[dict]:
    rows, _ = records(g, 1)
    out = []
    for r in rows:
        desc = r.get("description")
        if not desc:
            continue
        out.append({"date": parse_date(r.get("date_of_finding") or ""), "line": r.get("workshop_line"), "description": desc,
                    "severity": r.get("severity"), "process": r.get("process"),
                    "affectedModules": intval(r.get("no_of_affected_modules") or r.get("rejected_module_sr_no")),
                    "controlType": r.get("control_type"),
                    "vendorAction": r.get("vendor_immediate_action_containment") or r.get("vendor_containment_action"),
                    "closureStatus": r.get("closure_status")})
    return out


def nc_key(n: dict) -> tuple:
    d = n.get("date")
    return (d.date() if d else None, norm_key(n.get("process") or "")[:20], norm_key(n.get("description") or "")[:60])


# ------------------------------------------------------------------ quality roll-up
def _status(results: list[str | None]) -> str:
    rs = [r for r in results if r]
    if not rs:
        return "NA"
    if any(r == "FAIL" for r in rs):
        return "NOK"
    if any(r not in ("PASS",) for r in rs):
        return "WARN"
    return "OK"


def quality_checks(d: dict[str, Any]) -> list[dict]:
    checks = []

    def add(key, label, value, status):
        checks.append({"key": key, "label": label, "value": value, "status": status})
    ip = d["ipqc"]
    n_pass, n_fail = sum(1 for r in ip if r["result"] == "PASS"), sum(1 for r in ip if r["result"] == "FAIL")
    add("ipqc", "In-production quality control", f"{n_pass} pass / {n_fail} fail of {len(ip)} checks" if ip else "no data",
        _status([r["result"] for r in ip]))
    items = [m for b in d["bom"] for m in b["materials"]]
    recorded = [m for m in items if m["makeMatches"] is not None or m["originMatches"] is not None]
    differ = sum(1 for m in recorded if m["makeMatches"] is False or m["originMatches"] is False)
    add("bom", "BOM verification",
        f"{len(recorded) - differ} of {len(recorded)} as per BOM" + (f", {len(items) - len(recorded)} not recorded" if len(items) != len(recorded) else "") if items else "no data",
        "NA" if not recorded else ("OK" if not differ and all(m["result"] == "PASS" for m in recorded) else "WARN"))
    stor = [s for b in d["bom"] for s in b["storage"]]
    add("storage", "Material storage conditions", f"{sum(1 for s in stor if s['result'] == 'PASS')} of {len(stor)} pass" if stor else "no data",
        _status([s["result"] for s in stor]))
    fl = d["flasherResults"]
    devs = [abs(x) for x in (num((r.get("deviations") or "").replace("%", "")) for r in fl) if x is not None]
    add("flasher", "Sun simulator flash checks", f"max deviation {max(devs):.2f}% over {len(fl)} flashes" if devs else "no data",
        _status([result_of(r.get("i_v_curve_verification")) for r in fl] + [result_of(r.get("el_check")) for r in fl]))
    add("gel", "Gel content (cross-link)", d["gelOverall"] or "no data", _status([result_of(d["gelOverall"])]))
    add("dimension", "Dimension check", d["dimensionOverall"] or "no data", _status([result_of(d["dimensionOverall"])]))
    add("rfid", "RFID check", f"{len(d['rfid'])} modules" if d["rfid"] else "no data", _status([result_of(r.get("results")) for r in d["rfid"]]))
    add("finished", "Finished product storage", f"{len(d['finishedStorage'])} inspections" if d["finishedStorage"] else "no data",
        _status([result_of(r.get("inspection_results")) for r in d["finishedStorage"]]))
    dv = d["dataVerification"]
    add("data", "Manufacturing data verification", f"{len(dv)} checks" if dv else "no data", _status([result_of(r.get("sampled_data_results")) for r in dv]))
    cal = d["firstMeasurement"]
    add("calibration", "Sun simulator calibration", f"{len(cal)} measurements" if cal else "no data", _status([result_of(r.get("result")) for r in cal]))
    return checks


# ------------------------------------------------------------------ main entry
def parse_production_supervision(source) -> ParseResult:
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
    if "production supervision report" not in titles:
        err("WRONG_REPORT_TYPE", "This does not look like a Production Supervision report (title 'PRODUCTION SUPERVISION REPORT' not found). "
            "Check you selected the right module for this file.")
        return ParseResult(None, issues)

    report: dict[str, Any] = {"client": {}, "signatories": []}
    kv_info: dict[str, str] = {}
    sec: dict[str, list] = {k: [] for k in ("production", "qualification", "ipqc", "flasherVerification", "flasherResults", "soldering", "gel",
                                             "dimension", "rfid", "internalLab", "finishedStorage", "dataVerification", "firstMeasurement")}
    bom: list[dict] = []
    totals: dict | None = None
    ncs_cum: list[dict] = []
    ncs_sum: list[dict] = []
    ncs_rec: list[dict] = []
    overall = {"gel": None, "dimension": None}
    calibration: dict[str, Any] = {"basic": [], "reference": []}
    dimension_standard: dict | None = None
    line = shift = None
    current_bom: dict | None = None
    unreadable = 0

    for b in blocks:
        if isinstance(b, Paragraph):
            m = SECTION_RX.match(clean(b.text))
            if m:
                line, shift = " & ".join(re.findall(r"\d+", m.group(1))), m.group(2).capitalize()
                current_bom = None
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
        if kind == "production":
            rows, tot = parse_production(g, warn)
            sec["production"] += rows
            totals = totals or tot
        elif kind == "qualification":
            sec["qualification"] += parse_qualification(g, warn)
        elif kind == "bom":
            current_bom = {"line": line, "shift": shift, "materials": parse_bom(g, line, shift), "storage": []}
            bom.append(current_bom)
        elif kind == "storage":
            if current_bom is None or current_bom["line"] != line or current_bom["shift"] != shift:
                current_bom = {"line": line, "shift": shift, "materials": [], "storage": []}
                bom.append(current_bom)
            current_bom["storage"] += parse_storage(g)
        elif kind == "ipqc":
            sec["ipqc"] += parse_ipqc(g)
        elif kind == "nc_summary":
            ncs_sum += nc_from_table(g, False)
        elif kind == "nc_cumulative":
            ncs_cum += nc_from_table(g, True)
        elif kind == "nc_record":
            rec = parse_nc_record(b)
            if rec:
                ncs_rec.append(rec)
        elif kind == "soldering":
            sec["soldering"] += parse_soldering(g)
        elif kind == "gel":
            rows, ov = records(g, 1)
            sec["gel"] += rows
            overall["gel"] = ov or overall["gel"]
        elif kind == "dimension":
            rows, ov = records(g, 1)
            sec["dimension"] += [r for r in rows if norm_key(next(iter(r.values()), "") or "") != "standard values"]
            std = [r for r in rows if norm_key(next(iter(r.values()), "") or "") == "standard values"]
            dimension_standard = dimension_standard or (std[0] if std else None)
            overall["dimension"] = ov or overall["dimension"]
        elif kind in ("flasher_verification", "flasher_results", "rfid", "internal_lab", "finished_storage", "data_verification", "first_measurement"):
            key = {"flasher_verification": "flasherVerification", "flasher_results": "flasherResults", "rfid": "rfid",
                   "internal_lab": "internalLab", "finished_storage": "finishedStorage", "data_verification": "dataVerification",
                   "first_measurement": "firstMeasurement"}[kind]
            sec[key] += records(g, 1)[0]
        elif kind in ("calibration_basic", "calibration_reference"):
            pairs = [[r[0], val(r[1])] for r in g[1:] if len(r) > 1 and clean(r[0])]
            calibration["basic" if kind == "calibration_basic" else "reference"] += pairs
        elif kind == "signatories":
            for r in g:
                report["signatories"].append({"role": r[0], "designation": r[1] if len(r) > 1 else "", "name": ""})
    if unreadable:
        warn("TABLES_SKIPPED", f"{unreadable} table(s) could not be read and were skipped.")

    # ---- report header
    if not kv_info:
        err("REPORT_INFO_MISSING", "The 'Report No. / Report Date / Manufacturer / Location / Workshop' table was not found.")
        return ParseResult(None, issues)
    report_no = kv_info.get("report no", "")
    if is_blank(report_no):
        err("REPORT_NO_MISSING", "Report No. is empty or still a placeholder ('xxxxx'). Fill it in before uploading.")
    rd = parse_date(kv_info.get("report date", ""))
    if not rd:
        err("REPORT_DATE_INVALID", f"Report Date '{kv_info.get('report date', '')}' is not a valid date (expected e.g. 30.09.2026).")
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

    # ---- required content
    if not sec["production"]:
        err("PRODUCTION_TABLE_MISSING", "No daily rows found in the 'Production Snapshot' table (Date / Power Bin / Planned / Actual ...).")
    if any(i.level == "ERROR" for i in issues):
        return ParseResult(None, issues)
    for name, label in (("qualification", "Qualified & Rejected Modules"), ("ipqc", "In-Production Quality Control")):
        if not sec[name]:
            warn("SECTION_MISSING", f"'{label}' table not found; related widgets will be empty for this report.")
    if not bom:
        warn("SECTION_MISSING", "'List of Materials used' (BOM verification) not found.")

    # ---- cross-check production totals
    if totals and totals.get("actual") and totals["actual"]["qty"] is not None:
        s = sum((r["actual"] or {}).get("qty") or 0 for r in sec["production"])
        if s != totals["actual"]["qty"]:
            warn("PRODUCTION_TOTAL_MISMATCH", f"Production snapshot 'Total' says {totals['actual']['qty']:,} actual modules but the daily rows add up to {s:,}. "
                 "Dashboard uses the daily rows.")
    # ---- non-conformities: cumulative list is the base; current-day table + detailed records enrich/extend it
    # priority (later wins, None never overwrites): detailed record < cumulative table < current-day table
    ncs: dict[tuple, dict] = {}
    closures: dict[tuple, list[str]] = {}
    for n in ncs_rec + ncs_cum + ncs_sum:
        k = nc_key(n)
        ncs.setdefault(k, {}).update({x: v for x, v in n.items() if v is not None})
        closures.setdefault(k, []).append(n.get("closureStatus") or "")
    nc_list = []
    for k, n in ncs.items():
        sts = [nc_status(c) for c in closures[k]]
        n["status"] = "OPEN" if "OPEN" in sts else "CLOSED" if "CLOSED" in sts else "UNKNOWN"  # any open/pending mention keeps it open
        nc_list.append(n)
    nc_list.sort(key=lambda n: (n.get("date") or datetime.min))

    data = {"production": sec["production"], "productionTotal": totals, "qualification": sec["qualification"], "bom": bom,
            "ipqc": sec["ipqc"], "flasherVerification": sec["flasherVerification"], "flasherResults": sec["flasherResults"],
            "soldering": sec["soldering"], "gel": sec["gel"], "gelOverall": overall["gel"], "dimension": sec["dimension"],
            "dimensionStandard": dimension_standard, "dimensionOverall": overall["dimension"], "rfid": sec["rfid"],
            "internalLab": [r for r in sec["internalLab"] if any(v for k, v in r.items() if k != "module_sr_no")],
            "finishedStorage": sec["finishedStorage"], "dataVerification": sec["dataVerification"],
            "firstMeasurement": sec["firstMeasurement"], "calibration": calibration, "nonConformities": nc_list}
    data["quality"] = quality_checks(data)

    # ---- roll-up stored on the report
    cum = next((q for q in sec["qualification"] if q["kind"] == "cumulative"), None)
    dates = sorted({r["date"] for r in sec["production"]})
    items = [m for b in bom for m in b["materials"]]
    summary = {
        "days": len(dates), "firstDate": dates[0], "lastDate": dates[-1],
        "plannedQty": sum((r["planned"] or {}).get("qty") or 0 for r in sec["production"]),
        "actualQty": sum((r["actual"] or {}).get("qty") or 0 for r in sec["production"]),
        "actualMwp": round(sum((r["actual"] or {}).get("mwp") or 0 for r in sec["production"]), 3),
        "rejectedQty": ((cum or {}).get("rejected") or {}).get("qty"), "suspectedQty": ((cum or {}).get("suspected") or {}).get("qty"),
        "openNcs": sum(1 for n in nc_list if n["status"] == "OPEN"), "totalNcs": len(nc_list),
        "bomItems": len(items), "bomDiffer": sum(1 for m in items if m["makeMatches"] is False or m["originMatches"] is False),
        "ipqcChecks": len(sec["ipqc"]), "ipqcFail": sum(1 for r in sec["ipqc"] if r["result"] == "FAIL"),
    }
    data["summary"] = summary
    data["report"] = report
    issues.insert(0, Issue("INFO", "PARSED", f"Parsed report {report_no}: {summary['days']} production day(s), {summary['actualQty']:,} modules produced, "
                           f"{len(bom)} BOM section(s), {len(sec['ipqc'])} IPQC checks, {len(nc_list)} non-conformit{'y' if len(nc_list) == 1 else 'ies'}. "
                           "Media in the document was ignored."))
    if summary["bomDiffer"]:
        issues.append(Issue("INFO", "BOM_DIFFERENCES", f"{summary['bomDiffer']} BOM line(s) have actual make/origin text that differs from the BOM "
                            "(see the Production Supervision dashboard)."))
    return ParseResult(data, issues)
