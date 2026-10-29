from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import get_settings
from ..core.db import get_db
from ..core.security import create_token, hash_password, verify_password
from ..deps import get_current_user, public_user
from ..schemas import LoginIn, RegisterIn

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginIn):
    u = await get_db().users.find_one({"email": body.email})
    # same message for unknown email / wrong password
    if not u or not verify_password(body.password, u["passwordHash"]):
        raise HTTPException(401, "Incorrect email or password")
    if u["status"] == "pending":
        raise HTTPException(403, "Your account is awaiting administrator approval")
    if u["status"] == "disabled":
        raise HTTPException(403, "Your account has been disabled")
    return {"accessToken": create_token(str(u["_id"]), u["role"]), "tokenType": "bearer", "user": public_user(u)}


@router.post("/register", status_code=201)
async def register(body: RegisterIn):
    if not get_settings().allow_self_registration:
        raise HTTPException(403, "Self-registration is disabled; ask an administrator to create your account")
    db = get_db()
    if await db.users.find_one({"email": body.email}):
        raise HTTPException(409, "An account with this email already exists")
    await db.users.insert_one({"email": body.email, "name": body.name, "passwordHash": hash_password(body.password),
                               "role": "viewer", "status": "pending", "createdAt": datetime.now(timezone.utc)})
    return {"message": "Registration received. An administrator must approve your account before you can sign in."}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return public_user(user)
