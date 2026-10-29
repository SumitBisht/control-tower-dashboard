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
