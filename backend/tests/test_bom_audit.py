"""BOM Verification + Pre-Production Audit: parser tests (always run) + end-to-end API tests (need MongoDB)."""
import io
import os
from pathlib import Path

import pytest
from docx import Document

from app.modules.bom_verification.parser import parse_bom_verification
from app.modules.pre_production_audit.parser import parse_pre_production_audit

FIX = Path(__file__).parent / "fixtures"
B1, B2, A1 = "bom_2026-09-24.docx", "bom_2026-10-26.docx", "ppa_2026-09-27.docx"


def bom(name):
    return parse_bom_verification((FIX / name).read_bytes())


def ppa(name=A1):
    return parse_pre_production_audit((FIX / name).read_bytes())


def codes(r, level):
    return {i.code for i in r.issues if i.level == level}


def _walk(o):
    yield o
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from _walk(v)


def test_bom_september():
    r = bom(B1)
    assert r.ok, [i.message for i in r.errors]
    d = r.data
    assert d["report"]["reportNo"] == "DSR-BOM-RES-2026-09-24" and d["report"]["reportDate"].month == 9
    assert d["report"]["spvName"].startswith("Solapur Ganeko One") and d["report"]["projectName"] == "Ganeko Two Energy Pvt. Ltd."
    assert d["report"]["manufacturer"].startswith("Premier Energies") and d["report"]["workshop"] == "P7"
    assert len(d["materials"]) == 16 and len(d["storage"]) == 13
    cell = d["materials"][0]
    assert cell["material"] == "Solar Cell" and cell["bomOrigin"] == cell["actualOrigin"] == "Indonesia" and cell["result"] == "PASS" and cell["remarks"] is None
    assert cell["batchNo"] == "HN142000198L3A260707NP268415" and not cell["deviation"]
    # 'm²' vs 'm²²' in the source is a typo, not a deviation
    assert not any(m["deviation"] for m in d["materials"])
    assert d["materials"][3]["remarks"] == "Mostly expired in month end."
    conn = next(s for s in d["storage"] if s["material"] == "String Connector")
    assert conn["result"] == "UNDER REVIEW" and conn["temperatureC"] == 25.7 and conn["humidityPct"] == 59 and "0.40mm" in conn["observation"]
    s = d["summary"]
    assert (s["materials"], s["passed"], s["deviations"], s["storageItems"], s["storagePassed"], s["storageIssues"]) == (16, 16, 0, 13, 12, 1)
    assert not codes(r, "WARNING")


def test_bom_october_differs_in_batches_and_storage_result():
    d = bom(B2).data
    assert d["report"]["reportNo"] == "DSR-BOM-RES-2026-10-26" and d["report"]["reportDate"].month == 10
    assert d["materials"][0]["batchNo"] == "LN142000198L4A260714NP296380"
    assert d["summary"]["storagePassed"] == 13 and d["summary"]["storageIssues"] == 0


def test_bom_flags_a_real_deviation():
    d = Document(FIX / B1)
    t = next(t for t in d.tables if "As per BOM" in " ".join(c.text for c in t.rows[1].cells))
    row = t.rows[2]
    row.cells[2].paragraphs[0].runs[0].text = "Some Other Supplier ZX-1"
    for run in row.cells[2].paragraphs[0].runs[1:]:
        run.text = ""
    out = io.BytesIO()
    d.save(out)
    r = parse_bom_verification(out.getvalue())
    assert r.ok and r.data["materials"][0]["deviation"] and r.data["summary"]["deviations"] == 1
    assert {"BOM_DEVIATION", "PASS_WITH_DEVIATION"} <= codes(r, "WARNING")


def test_ppa():
    r = ppa()
    assert r.ok, [i.message for i in r.errors]
    d = r.data
    rep = d["report"]
    assert rep["reportNo"] == "DSR-PPA-RES-2026-09-27" and rep["reportDate"].day == 27 and rep["workshop"] == "P7"
    assert rep["spvName"] == "Solapur Ganeko One Energy Pvt. Ltd. - Shell - 22.9 MWp Solar"  # first of the listed SPVs
    assert rep["conclusion"] == "READY" and rep["audit"]["type"] == "Pre-Production Audit" and rep["audit"]["auditDate"] == "23-Sep-2026 And 25-Sep-2026"
    assert rep["audit"]["factory"].startswith("Premier Energies") and rep["audit"]["site"] == "Hyderabad"
    assert [s["role"] for s in rep["signatories"]] == ["PREPARED BY", "REVIEWED BY", "APPROVED BY"]
    assert len(d["checks"]) == 29 and list(d["extra"]["sections"]) == [
        "Raw Material Readiness Verification", "Manufacturing Equipment Certification & Calibration", "Workshop Manpower Readiness",
        "Pre-Shipment Stage: Testing & Internal Lab Readiness", "Packaging Readiness", "Dispatch & Loading Readiness"]
    first = d["checks"][0]
    assert first["item"] == "Approved BOM Alignment" and first["status"] == "CLOSED" and first["statusNote"] == "First 50MW"
    assert first["section"] == "Raw Material Readiness Verification" and all(c["status"] == "CLOSED" for c in d["checks"])
    assert len(d["ncs"]) == 9 and d["ncs"][0]["date"].day == 23 and d["ncs"][0]["severity"] == "Major" and d["ncs"][0]["process"] == "Stringer"
    assert d["ncs"][4]["statusNote"] == "First 50MW" and d["ncs"][8]["severity"] == "Minor"
    s = d["summary"]
    assert (s["checks"], s["checksClosed"], s["checksConditional"], s["ncTotal"], s["ncMajor"], s["ncMinor"], s["ncOpen"]) == (29, 29, 1, 9, 8, 1, 0)
    assert not codes(r, "WARNING")


def test_ppa_warns_when_ready_but_open_items():
    d = Document(FIX / A1)
    nc = next(t for t in d.tables if "Closure Status" in " ".join(c.text for c in t.rows[0].cells))
    cell = nc.rows[1].cells[5]
    cell.paragraphs[0].runs[0].text = "Open"
    for run in cell.paragraphs[0].runs[1:]:
        run.text = ""
    out = io.BytesIO()
    d.save(out)
    r = parse_pre_production_audit(out.getvalue())
    assert r.ok and r.data["summary"]["ncOpen"] == 1 and "CONCLUSION_CONFLICT" in codes(r, "WARNING")


def test_no_media_is_read_or_returned():
    for data in (bom(B1).data, bom(B2).data, ppa().data):
        items = list(_walk(data))
        assert not [x for x in items if isinstance(x, (bytes, bytearray))]
        assert not [x for x in items if isinstance(x, str) and x.lower() in ("photos", "photo", "media", "images")]
    assert "Media in the document was ignored" in bom(B1).issues[0].message
    assert "Media in the document was ignored" in ppa().issues[0].message


def test_wrong_type_and_garbage():
    assert "WRONG_REPORT_TYPE" in codes(parse_bom_verification((FIX / A1).read_bytes()), "ERROR")
    assert "WRONG_REPORT_TYPE" in codes(parse_pre_production_audit((FIX / B1).read_bytes()), "ERROR")
    assert "WRONG_REPORT_TYPE" in codes(parse_bom_verification((FIX / "psi_lot-1.docx").read_bytes()), "ERROR")
    for fn in (parse_bom_verification, parse_pre_production_audit):
        for payload in (b"", b"nope", b"PK\x03\x04junk"):
            r = fn(payload)
            assert not r.ok and r.errors
        buf = io.BytesIO()
        Document().save(buf)
        assert "WRONG_REPORT_TYPE" in codes(fn(buf.getvalue()), "ERROR")


def test_missing_tables_and_placeholder_report_no_are_errors():
    d = Document(FIX / B1)
    for t in list(d.tables):
        if "As per BOM" in " ".join(c.text for c in t.rows[-1].cells + t.rows[min(1, len(t.rows) - 1)].cells):
            t._tbl.getparent().remove(t._tbl)
    out = io.BytesIO()
    d.save(out)
    assert "MATERIALS_MISSING" in codes(parse_bom_verification(out.getvalue()), "ERROR")
    d = Document(FIX / A1)
    for t in list(d.tables):
        if t.rows[0].cells[0].text.strip().lower().startswith(("verification item", "equipment", "checklist item", "stage")):
            t._tbl.getparent().remove(t._tbl)
    out = io.BytesIO()
    d.save(out)
    assert "CHECKS_MISSING" in codes(parse_pre_production_audit(out.getvalue()), "ERROR")
    d = Document(FIX / A1)
    t = next(t for t in d.tables if t.rows[0].cells[0].text.strip() == "Report No.")
    run = t.rows[0].cells[1].paragraphs[0].runs
    run[0].text = ": xxxxx"
    for x in run[1:]:
        x.text = ""
    out = io.BytesIO()
    d.save(out)
    assert "REPORT_NO_MISSING" in codes(parse_pre_production_audit(out.getvalue()), "ERROR")


# --------------------------------------------------------------------------- end to end (MongoDB)
from test_api import _mongo_up, client, login, upload_and_wait  # noqa: E402,F401

needs_mongo = pytest.mark.skipif(not _mongo_up(), reason="MongoDB not reachable")


@needs_mongo
async def test_bom_upload_dashboard_reports_export(client):
    c, M = client, "bom_verification"
    admin = await login(c, "admin@test.io", "AdminPass123")
    root = Path(os.environ["STORAGE_LOCAL_DIR"])
    before = {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()

    for name in (B1, B2):
        up = await upload_and_wait(c, admin, name, (FIX / name).read_bytes(), module=M)
        assert up["status"] in ("SUCCESS", "SUCCESS_WITH_WARNINGS"), up["logs"]
    assert (await upload_and_wait(c, admin, B1, (FIX / B1).read_bytes(), module=M))["status"] == "FAILED"  # duplicate
    assert (await upload_and_wait(c, admin, B1, (FIX / B1).read_bytes(), module=M, replace="true"))["status"] != "FAILED"
    wrong = await upload_and_wait(c, admin, "x.docx", (FIX / A1).read_bytes(), module=M)
    assert wrong["status"] == "FAILED" and any(x["code"] == "WRONG_REPORT_TYPE" for x in wrong["logs"])

    w = (await c.get(f"/{M}/dashboard", headers=admin)).json()["widgets"]
    assert w["kpi_bom_reports"] == {"value": 2, "latest": "2026-10-26"}
    assert w["kpi_bom_pass"]["value"] == 100.0 and w["kpi_bom_pass"]["materials"] == 16  # KPIs describe the latest verification
    assert w["kpi_bom_deviations"]["value"] == 0
    assert w["kpi_bom_storage"]["value"] == 100.0 and w["kpi_bom_storage"]["items"] == 13
    assert [d["date"] for d in w["bom_results"]["data"]] == ["2026-09-24", "2026-10-26"] and w["bom_results"]["data"][0]["Pass"] == 16
    assert [r["report_date"] for r in w["bom_reports"]["rows"]] == ["2026-10-26", "2026-09-24"]
    assert len(w["bom_materials"]["rows"]) == 32 and w["bom_materials"]["rows"][0]["report_date"] == "2026-10-26"
    assert len(w["bom_storage"]["rows"]) == 26

    f = (await c.get(f"/{M}/filters", headers=admin)).json()
    assert len(f["project"]) == 1 and f["manufacturer"][0].startswith("Premier")
    one = (await c.get(f"/{M}/dashboard?date_from=2026-09-01&date_to=2026-09-30", headers=admin)).json()["widgets"]
    assert one["kpi_bom_reports"]["value"] == 1 and len(one["bom_materials"]["rows"]) == 16
    assert one["kpi_bom_storage"]["value"] == round(100 * 12 / 13, 1)
    assert (await c.get(f"/{M}/dashboard?date_from=2026-10-09&date_to=2026-10-01", headers=admin)).status_code == 422

    assert (await c.put(f"/admin/widgets/{M}/kpi_bom_pass", headers=admin, json={"visible": False})).status_code == 200
    assert (await c.put(f"/admin/widgets/{M}/bom_materials", headers=admin, json={"columns": {"batch_no": False}})).status_code == 200
    w2 = (await c.get(f"/{M}/dashboard", headers=admin)).json()["widgets"]
    assert "kpi_bom_pass" not in w2 and "batch_no" not in w2["bom_materials"]["rows"][0] and "material" in w2["bom_materials"]["rows"][0]

    rep = (await c.get(f"/{M}/reports", headers=admin)).json()
    assert rep["total"] == 2 and rep["items"][0]["reportNo"] == "DSR-BOM-RES-2026-10-26" and rep["items"][0]["materials"] == 16
    assert (await c.get(f"/{M}/reports?q=2026-09-24", headers=admin)).json()["total"] == 1
    detail = (await c.get(f"/{M}/reports/{rep['items'][0]['id']}", headers=admin)).json()
    assert len(detail["materials"]) == 16 and len(detail["storage"]) == 13
    x = await c.get(f"/{M}/reports/export?format=xlsx", headers=admin)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(x.content), read_only=True)
    assert set(wb.sheetnames) == {"Materials", "Reports", "Storage"} and len(list(wb["Materials"].iter_rows(values_only=True))) == 1 + 32
    assert (await c.get(f"/{M}/reports/export?format=csv&q=2026-09-24", headers=admin)).text.count("DSR-BOM-RES-2026-09-24") == 16
    assert (await c.get(f"/{M}/reports/export?q=nomatch", headers=admin)).status_code == 404

    assert ({p for p in root.rglob("*") if p.is_file()} if root.exists() else set()) == before  # nothing (no media, no .docx) stored

    ups = (await c.get("/uploads", headers=admin)).json()
    target = next(u for u in ups if u["module"] == M and u["status"].startswith("SUCCESS") and u["summary"]["reportNo"] == "DSR-BOM-RES-2026-10-26")
    assert (await c.delete(f"/uploads/{target['id']}", headers=admin)).status_code == 204
    assert (await c.get(f"/{M}/reports", headers=admin)).json()["total"] == 1


@needs_mongo
async def test_ppa_upload_dashboard_reports_export(client):
    c, M = client, "pre_production_audit"
    admin = await login(c, "admin@test.io", "AdminPass123")
    root = Path(os.environ["STORAGE_LOCAL_DIR"])
    before = {p for p in root.rglob("*") if p.is_file()} if root.exists() else set()

    up = await upload_and_wait(c, admin, A1, (FIX / A1).read_bytes(), module=M)
    assert up["status"] in ("SUCCESS", "SUCCESS_WITH_WARNINGS"), up["logs"]
    assert (await upload_and_wait(c, admin, A1, (FIX / A1).read_bytes(), module=M))["status"] == "FAILED"  # duplicate
    wrong = await upload_and_wait(c, admin, "x.docx", (FIX / B1).read_bytes(), module=M)
    assert wrong["status"] == "FAILED" and any(x["code"] == "WRONG_REPORT_TYPE" for x in wrong["logs"])

    w = (await c.get(f"/{M}/dashboard", headers=admin)).json()["widgets"]
    assert w["kpi_ppa_audits"] == {"value": 1, "latest": "READY", "latestDate": "2026-09-27"}
    assert w["kpi_ppa_checks"] == {"value": 100.0, "closed": 29, "checks": 29, "conditional": 1}
    assert w["kpi_ppa_nc"] == {"value": 9, "major": 8, "minor": 1} and w["kpi_ppa_open"] == {"value": 0, "closed": 9}
    assert w["ppa_nc_trend"]["data"] == [{"date": "2026-09-23", "Major": 3, "Minor": 0}, {"date": "2026-09-24", "Major": 4, "Minor": 0},
                                         {"date": "2026-09-25", "Major": 1, "Minor": 1}]
    assert w["ppa_audits"]["rows"][0]["checks"] == "29 / 29" and w["ppa_audits"]["rows"][0]["conclusion"] == "READY"
    assert len(w["ppa_sections"]["rows"]) == 6 and len(w["ppa_checks"]["rows"]) == 29 and len(w["ppa_nonconformities"]["rows"]) == 9
    assert w["ppa_checks"]["rows"][0]["note"] == "First 50MW"

    assert (await c.put(f"/admin/widgets/{M}/kpi_ppa_nc", headers=admin, json={"visible": False})).status_code == 200
    assert (await c.put(f"/admin/widgets/{M}/ppa_checks", headers=admin, json={"columns": {"evidence": False}})).status_code == 200
    w2 = (await c.get(f"/{M}/dashboard", headers=admin)).json()["widgets"]
    assert "kpi_ppa_nc" not in w2 and "evidence" not in w2["ppa_checks"]["rows"][0] and "item" in w2["ppa_checks"]["rows"][0]

    rep = (await c.get(f"/{M}/reports", headers=admin)).json()
    assert rep["total"] == 1 and rep["items"][0]["conclusion"] == "READY" and rep["items"][0]["ncTotal"] == 9
    assert (await c.get(f"/{M}/reports?q=Hyderabad", headers=admin)).json()["total"] == 1
    assert (await c.get(f"/{M}/reports?q=nomatch", headers=admin)).json()["total"] == 0
    detail = (await c.get(f"/{M}/reports/{rep['items'][0]['id']}", headers=admin)).json()
    assert len(detail["checks"]) == 29 and len(detail["nonConformities"]) == 9 and detail["report"]["audit"]["sequence"] == "Initial"
    x = await c.get(f"/{M}/reports/export?format=xlsx", headers=admin)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(x.content), read_only=True)
    assert set(wb.sheetnames) == {"Checklist", "Reports", "Non-conformities"} and len(list(wb["Non-conformities"].iter_rows(values_only=True))) == 1 + 9
    assert (await c.get(f"/{M}/reports/export?format=csv", headers=admin)).text.count("DSR-PPA-RES-2026-09-27") == 29

    assert ({p for p in root.rglob("*") if p.is_file()} if root.exists() else set()) == before

    ups = (await c.get("/uploads", headers=admin)).json()
    target = next(u for u in ups if u["module"] == M and u["status"].startswith("SUCCESS"))
    assert (await c.delete(f"/uploads/{target['id']}", headers=admin)).status_code == 204
    assert (await c.get(f"/{M}/reports", headers=admin)).json()["total"] == 0
