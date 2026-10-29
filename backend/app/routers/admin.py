from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException

from ..core.db import get_db
from ..core.security import hash_password
from ..deps import public_user, require_admin
from ..modules.registry import get_module
from ..schemas import UserCreateIn, UserUpdateIn, WidgetSettingIn
from ..widgets import get_widget_settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except InvalidId:
        raise HTTPException(404, "Not found")


async def _active_admins(db) -> int:
    return await db.users.count_documents({"role": "admin", "status": "active"})


@router.get("/users")
async def list_users(status: str | None = None, admin=Depends(require_admin)):
    q = {"status": status} if status else {}
    return [public_user(u) async for u in get_db().users.find(q).sort("createdAt", -1)]


@router.post("/users", status_code=201)
async def create_user(body: UserCreateIn, admin=Depends(require_admin)):
    db = get_db()
    if await db.users.find_one({"email": body.email}):
        raise HTTPException(409, "An account with this email already exists")
    doc = {"email": body.email, "name": body.name, "passwordHash": hash_password(body.password), "role": body.role,
           "status": "active", "createdAt": datetime.now(timezone.utc), "createdBy": admin["email"]}
    doc["_id"] = (await db.users.insert_one(doc)).inserted_id
    return public_user(doc)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdateIn, admin=Depends(require_admin)):
    db, oid = get_db(), _oid(user_id)
    u = await db.users.find_one({"_id": oid})
    if not u:
        raise HTTPException(404, "User not found")
    upd = {}
    if body.name:
        upd["name"] = body.name.strip()
    if body.role:
        upd["role"] = body.role
    if body.status:
        upd["status"] = body.status
    if body.password:
        if len(body.password) < 4:
            raise HTTPException(422, "password must be at least 4 characters")
        upd["passwordHash"] = hash_password(body.password)
    losing_admin = u["role"] == "admin" and u["status"] == "active" and (
        upd.get("role", "admin") != "admin" or upd.get("status", "active") != "active")
    if losing_admin and await _active_admins(db) <= 1:
        raise HTTPException(400, "Cannot demote or disable the last active administrator")
    if body.status == "active" and u["status"] == "pending":
        upd["approvedBy"], upd["approvedAt"] = admin["email"], datetime.now(timezone.utc)
    if upd:
        await db.users.update_one({"_id": oid}, {"$set": upd})
    return public_user(await db.users.find_one({"_id": oid}))


@router.post("/users/{user_id}/approve")
async def approve_user(user_id: str, admin=Depends(require_admin)):
    return await update_user(user_id, UserUpdateIn(status="active"), admin)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, admin=Depends(require_admin)):
    db, oid = get_db(), _oid(user_id)
    u = await db.users.find_one({"_id": oid})
    if not u:
        raise HTTPException(404, "User not found")
    if u["_id"] == admin["_id"]:
        raise HTTPException(400, "You cannot delete your own account")
    if u["role"] == "admin" and u["status"] == "active" and await _active_admins(db) <= 1:
        raise HTTPException(400, "Cannot delete the last active administrator")
    await db.users.delete_one({"_id": oid})


@router.get("/widgets/{module_key}")
async def list_widgets(module_key: str, admin=Depends(require_admin)):
    m = get_module(module_key)
    if not m:
        raise HTTPException(404, "Unknown module")
    return list((await get_widget_settings(get_db(), m)).values())


@router.put("/widgets/{module_key}/{widget_key}")
async def set_widget(module_key: str, widget_key: str, body: WidgetSettingIn, admin=Depends(require_admin)):
    m = get_module(module_key)
    w = next((w for w in m.widgets if w.key == widget_key), None) if m else None
    if not w:
        raise HTTPException(404, "Unknown widget")
    upd = {}
    if body.visible is not None:
        upd["visible"] = body.visible
    if body.columns is not None:
        valid = {c.key for c in w.columns}
        bad = set(body.columns) - valid
        if bad:
            raise HTTPException(422, f"Unknown column(s): {', '.join(sorted(bad))}")
        merged = {**{c: True for c in valid}, **body.columns}
        if w.columns and not any(merged.values()):
            raise HTTPException(422, "At least one column must stay visible (hide the whole widget instead)")
        upd.update({f"columns.{k}": v for k, v in body.columns.items()})
    if upd:
        await get_db().widget_settings.update_one({"module": module_key, "widgetKey": widget_key}, {"$set": upd}, upsert=True)
    return (await get_widget_settings(get_db(), m))[widget_key]
