import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .core.db import get_db
from .core.security import decode_token

bearer = HTTPBearer(auto_error=False)


def public_user(u: dict) -> dict:
    return {"id": str(u["_id"]), "email": u["email"], "name": u["name"], "role": u["role"], "status": u["status"],
            "createdAt": u.get("createdAt")}


async def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(cred.credentials)
        user = await get_db().users.find_one({"_id": ObjectId(payload["sub"])})
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired token")
    if not user or user["status"] != "active":
        raise HTTPException(401, "Account is not active")
    return user


def require_roles(*roles: str):
    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "You do not have permission to do this")
        return user

    return dep


require_admin = require_roles("admin")
require_uploader = require_roles("uploader", "admin")
