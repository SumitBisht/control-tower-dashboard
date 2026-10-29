"""End-to-end API test against a real MongoDB (skipped if none is reachable). Uses a throw-away database."""
import os
import uuid

import pymongo
import pytest
from httpx import ASGITransport, AsyncClient
from pathlib import Path

URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB = f"ct_test_{uuid.uuid4().hex[:8]}"
os.environ.update({"MONGODB_DB": DB, "MONGODB_URI": URI, "STORAGE_LOCAL_DIR": f"./.test_storage/{DB}",
                   "ADMIN_EMAIL": "admin@test.io", "ADMIN_PASSWORD": "AdminPass123"})

FIX = Path(__file__).parent / "fixtures"


def _mongo_up() -> bool:
    try:
        pymongo.MongoClient(URI, serverSelectionTimeoutMS=1500).admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _mongo_up(), reason="MongoDB not reachable")


@pytest.fixture
async def client():
    from app.core.db import close_db, get_db
    from app.main import app, bootstrap

    await bootstrap(get_db())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t/api") as c:
        yield c
    await get_db().client.drop_database(DB)
    await close_db()


async def login(c, email, pw):
    r = await c.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


async def test_full_flow(client):
    c = client
    admin = await login(c, "admin@test.io", "AdminPass123")

    # self-registration -> pending -> cannot log in -> admin approves
    assert (await c.post("/auth/register", json={"name": "V", "email": "v@t.io", "password": "password1"})).status_code == 201
    assert (await c.post("/auth/login", json={"email": "v@t.io", "password": "password1"})).status_code == 403
    uid = next(u["id"] for u in (await c.get("/admin/users", headers=admin)).json() if u["email"] == "v@t.io")
    assert (await c.post(f"/admin/users/{uid}/approve", headers=admin)).status_code == 200
    viewer = await login(c, "v@t.io", "password1")

    # roles
    assert (await c.get("/admin/users", headers=viewer)).status_code == 403
    r = await c.post("/uploads", headers=viewer, files={"file": ("a.docx", b"x")})
    assert r.status_code == 403
    assert (await c.post("/admin/users", headers=admin, json={"name": "U", "email": "u@t.io", "password": "password1", "role": "uploader"})).status_code == 201
    uploader = await login(c, "u@t.io", "password1")

    # last admin protection
    me = (await c.get("/auth/me", headers=admin)).json()
    assert (await c.patch(f"/admin/users/{me['id']}", headers=admin, json={"role": "viewer"})).status_code == 400

    # failed uploads terminate gracefully and save nothing
    for name, data in [("x.pdf", b"%PDF"), ("bad.docx", b"not a zip"), ("tpl.docx", (FIX / "template.docx").read_bytes())]:
        r = await c.post("/uploads", headers=uploader, files={"file": (name, data)})
        assert r.status_code == 200 and r.json()["status"] == "FAILED", name
        assert any(line["level"] == "ERROR" for line in r.json()["logs"])
    assert (await c.get("/container_loading/dashboard", headers=viewer)).json()["widgets"]["kpi_containers"]["value"] == 0

    # good upload
    good = (FIX / "sample_valid.docx").read_bytes()
    r = await c.post("/uploads", headers=uploader, files={"file": ("ok.docx", good)}, data={"project_name": "Proj A"})
    assert r.json()["status"] == "SUCCESS_WITH_WARNINGS", r.json()["logs"]
    r2 = await c.post("/uploads", headers=uploader, files={"file": ("ok.docx", good)})
    assert r2.json()["status"] == "FAILED"  # duplicate
    assert (await c.post("/uploads", headers=uploader, files={"file": ("ok.docx", good)}, data={"replace": "true"})).json()["status"] != "FAILED"

    w = (await c.get("/container_loading/dashboard", headers=viewer)).json()["widgets"]
    assert w["kpi_containers"]["value"] == 12 and w["kpi_modules"]["value"] == 8640
    assert w["kpi_capacity"]["value"] == 4.752
    assert w["product_summary"]["rows"][0]["containers"] == 12
    assert w["loading_trend"]["cumulative"] and w["loading_trend"]["data"][-1]["550 Wp"] == 8640
    assert {r["item"]: r["status"] for r in w["checklist_summary"]["rows"]}["Shock Label Validations"] == "NA"
    assert (await c.get("/container_loading/dashboard?project=Nope", headers=viewer)).json()["widgets"]["kpi_containers"]["value"] == 0

    # widget + column hiding is enforced server-side
    assert (await c.put("/admin/widgets/container_loading/kpi_modules", headers=admin, json={"visible": False})).status_code == 200
    assert (await c.put("/admin/widgets/container_loading/product_summary", headers=admin, json={"columns": {"modules": False}})).status_code == 200
    w = (await c.get("/container_loading/dashboard", headers=viewer)).json()["widgets"]
    assert "kpi_modules" not in w
    assert "modules" not in w["product_summary"]["rows"][0]
    assert (await c.put("/admin/widgets/container_loading/product_summary", headers=admin, json={"columns": {"bogus": False}})).status_code == 422
