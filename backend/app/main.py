import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.db import close_db, get_db
from .core.security import hash_password
from .deps import get_current_user
from .modules.registry import MODULES
from .routers import admin, auth, uploads
from .uploads import fail_interrupted_uploads
from .widgets import get_widget_settings

logging.basicConfig(level=logging.INFO)


async def bootstrap(db) -> None:
    s = get_settings()
    await db.users.create_index("email", unique=True)
    await db.uploads.create_index([("uploadedAt", -1)])
    await db.uploads.create_index("fileHash")
    await db.widget_settings.create_index([("module", 1), ("widgetKey", 1)], unique=True)
    for m in MODULES.values():
        await m.ensure_indexes(db)
    await fail_interrupted_uploads(db)
    if not await db.users.find_one({"role": "admin"}):
        await db.users.insert_one({"email": s.admin_email.lower(), "name": s.admin_name, "role": "admin", "status": "active",
                                   "passwordHash": hash_password(s.admin_password), "createdAt": datetime.now(timezone.utc)})
        logging.getLogger("bootstrap").warning("Seeded initial admin %s - change the password immediately", s.admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bootstrap(get_db())
    yield
    await close_db()


app = FastAPI(title="Control Tower API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])

api = APIRouter(prefix="/api")
api.include_router(auth.router)
api.include_router(admin.router)
api.include_router(uploads.router)


@api.get("/config")
async def public_config():
    """Non-secret display settings (no auth: the login page uses it too)."""
    s = get_settings()
    return {"clientName": s.client_name, "appName": s.app_name}


@api.get("/modules")
async def list_modules(user=Depends(get_current_user)):
    out = []
    for m in MODULES.values():
        ws = await get_widget_settings(get_db(), m)
        out.append({"key": m.key, "title": m.title, "widgets": [w for w in ws.values() if w["visible"]]})
    return out


for _m in MODULES.values():  # each module contributes its own routes under /api/<module key>/...
    api.include_router(_m.router())

app.include_router(api)


@app.get("/health")
async def health():
    return {"status": "ok"}
