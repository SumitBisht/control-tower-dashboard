"""Shared helpers for parsing DSR Word reports (python-docx). Pure functions, no I/O."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from docx.table import Table
from docx.text.paragraph import Paragraph

DATE_FORMATS = ("%d.%m.%Y %H:%M", "%d-%m-%Y %H:%M", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d")


# ---------- small helpers ----------
def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def is_blank(s: str) -> bool:
    return not s or bool(re.fullmatch(r"x+", s.strip().lower()))


def strip_colon(s: str) -> str:
    return clean(re.sub(r"^\s*:\s*", "", s or ""))


def parse_date(s: str) -> datetime | None:
    s = clean(s)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def parse_int(s: str) -> int | None:
    m = re.search(r"-?\d[\d,]*", s or "")
    return int(m.group().replace(",", "")) if m else None


def parse_float(s: str) -> float | None:
    m = re.search(r"-?\d[\d,]*\.?\d*", s or "")
    return float(m.group().replace(",", "")) if m else None


def parse_dims(s: str) -> list[float] | None:
    parts = re.findall(r"\d+(?:\.\d+)?", s or "")
    return [float(p) for p in parts[:3]] if len(parts) >= 3 else None


def row_cells(row) -> list[str]:
    return [clean(c.text) for c in row.cells]


def kv_of(table: Table) -> dict[str, str]:
    """Flatten label|value|label|value rows into {normalised label: value}."""
    out: dict[str, str] = {}
    for row in table.rows:
        cells, seen, uniq = row.cells, set(), []
        for c in cells:
            if id(c._tc) not in seen:
                seen.add(id(c._tc))
                uniq.append(clean(c.text))
        for i in range(0, len(uniq) - 1, 2):
            if uniq[i]:
                out.setdefault(norm_key(uniq[i]), strip_colon(uniq[i + 1]))
    return out


def kv_get(kv: dict[str, str], prefix: str) -> str | None:
    for k, v in kv.items():
        if k.startswith(prefix):
            return v
    return None


def iter_blocks(doc):
    for el in doc.element.body.iterchildren():
        if el.tag.endswith("}p"):
            yield Paragraph(el, doc)
        elif el.tag.endswith("}tbl"):
            yield Table(el, doc)




MAX_TABLE_ROWS = 5000
PASS = {"pass", "passed", "ok", "okay"}
FAIL = {"fail", "failed", "nok"}


# ---------- generic table / value helpers ----------
def snake(s: str) -> str:
    return re.sub(r"\s+", "_", norm_key(s))[:60] or "col"


def val(x: str | None) -> str | None:
    x = clean(x)
    return None if x in ("", "/", "-") else x


def num(x: str | None) -> float | None:
    v = parse_float(x or "") if x and re.search(r"\d", x) else None
    return v


def intval(x: str | None) -> int | None:
    f = num(x)
    return int(round(f)) if f is not None else None


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", (s or "").lower()))


def result_of(s: str | None) -> str | None:
    v = norm_key(s or "")
    if v in PASS:
        return "PASS"
    if v in FAIL:
        return "FAIL"
    if v in ("", "n a", "na", "nil", "not applicable"):
        return None
    return v.upper()  # e.g. UNDER REVIEW


def grid(table: Table) -> list[list[str]]:
    return [row_cells(r) for r in table.rows[:MAX_TABLE_ROWS]]


def head_text(g: list[list[str]], n: int = 3) -> str:
    return norm_key(" ".join(" ".join(r) for r in g[:n]))


def records(g: list[list[str]], header_rows: int) -> tuple[list[dict[str, Any]], str | None]:
    """Generic table -> list of {snake_case_header: value}. Returns (rows, overall_result)."""
    ncol = max((len(r) for r in g), default=0)
    keys: list[str] = []
    for j in range(ncol):
        parts: list[str] = []
        for r in g[:header_rows]:
            t = r[j] if j < len(r) else ""
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        k = snake(" ".join(parts))
        while k in keys:
            k += "_2"
        keys.append(k)
    out, overall = [], None
    for r in g[header_rows:]:
        if not any(r):
            continue
        if norm_key(r[0]).startswith("overall result"):
            overall = next((c for c in reversed(r) if c), None)
            continue
        out.append({keys[j]: val(r[j]) for j in range(min(len(keys), len(r)))})
    return out, overall


def open_docx(source, title_key: str, title: str):
    """Open an uploaded .docx and check the report title. Returns (doc, blocks, error Issue | None)."""
    import io
    import zipfile

    from docx import Document

    from .base import Issue
    src = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source)
    if not zipfile.is_zipfile(src):
        return None, [], Issue("ERROR", "NOT_DOCX", "The file is not a valid .docx document (legacy .doc, corrupted, or renamed file).")
    if isinstance(src, io.BytesIO):
        src.seek(0)
    try:
        doc = Document(src)
    except Exception as e:  # noqa: BLE001
        return None, [], Issue("ERROR", "DOCX_UNREADABLE", f"The Word document could not be opened: {type(e).__name__}.")
    blocks = list(iter_blocks(doc))
    titles = [norm_key(b.text) for b in blocks[:40] if isinstance(b, Paragraph)]
    if not any(title_key in t for t in titles):
        return None, [], Issue("ERROR", "WRONG_REPORT_TYPE", f"This does not look like a {title} report (title not found). Check you selected the right module for this file.")
    return doc, blocks, None


def read_header(blocks, issues: list, report: dict) -> bool:
    """Fill report{client, spvName, projectName, reportNo, reportDate, manufacturer, location, workshop} from the cover tables.
    Appends ERROR/WARNING issues; returns False when the report can't be identified."""
    from .base import Issue
    info: dict[str, str] = {}
    for b in blocks:
        if not isinstance(b, Table):
            continue
        try:
            kv = kv_of(b)
        except Exception:  # noqa: BLE001
            continue
        if "report no" in kv:
            info = kv
        if "spv name" in kv or "project name" in kv:
            report["client"] = {"name": kv.get("client", "")}
            report["spvName"], report["projectName"] = kv.get("spv name", "").rstrip(" -"), kv.get("project name", "").rstrip(" -")
            for row in b.rows:  # the SPV cell can list several SPVs on separate lines: the first one is the SPV of this report
                cells = [c.text for c in row.cells]
                if cells and norm_key(cells[0]) == "spv name" and len(cells) > 1:
                    first = next((ln for ln in (strip_colon(x) for x in cells[1].splitlines()) if ln), "")
                    report["spvName"] = first.rstrip(" -") or report["spvName"]
    if not info:
        issues.append(Issue("ERROR", "REPORT_INFO_MISSING", "The 'Report No. / Report Date / Manufacturer / Location / Workshop' table was not found."))
        return False
    ok = True
    report_no = info.get("report no", "")
    if is_blank(report_no):
        issues.append(Issue("ERROR", "REPORT_NO_MISSING", "Report No. is empty or still a placeholder ('xxxxx'). Fill it in before uploading."))
        ok = False
    rd = parse_date(info.get("report date", ""))
    if not rd:
        issues.append(Issue("ERROR", "REPORT_DATE_INVALID", f"Report Date '{info.get('report date', '')}' is not a valid date (expected e.g. 24-09-2026)."))
        ok = False
    for k, label in (("manufacturer", "Manufacturer"), ("location", "Location"), ("workshop", "Workshop")):
        v = info.get(k, "")
        if is_blank(v):
            issues.append(Issue("WARNING", "HEADER_FIELD_BLANK", f"{label} is blank or a placeholder."))
            v = "Unknown" if k == "manufacturer" else ""
        report[k] = v
    report.update(reportNo=report_no, reportDate=rd)
    if not report.get("spvName"):
        issues.append(Issue("WARNING", "SPV_MISSING", "SPV name not found in the document; set it on the upload form."))
    if not report.get("projectName"):
        issues.append(Issue("WARNING", "PROJECT_MISSING", "Project name not found in the document; set it on the upload form."))
    return ok
