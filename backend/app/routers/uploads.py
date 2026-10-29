from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..core.config import get_settings
from ..core.db import get_db
from ..core.storage import get_storage
from ..deps import require_admin, require_uploader
from ..modules.registry import get_module
from ..uploads import process_upload, serialize_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("")
async def upload(file: UploadFile = File(...), module: str = Form("container_loading"), spv_name: str = Form(""),
                 project_name: str = Form(""), replace: bool = Form(False), user=Depends(require_uploader)):
    m = get_module(module)
    if not m:
        raise HTTPException(404, "Unknown module")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = bytearray()
    while chunk := await file.read(1024 * 1024):  # bounded read: never hold an oversized file in memory
        data += chunk
        if len(data) > limit:
            raise HTTPException(413, f"File is larger than the {get_settings().max_upload_mb} MB limit")
    options = {"spv_name": spv_name.strip(), "project_name": project_name.strip(), "replace": replace}
    return await process_upload(get_db(), m, user, file.filename or "upload.docx", bytes(data), options)


@router.get("")
async def list_uploads(user=Depends(require_uploader)):
    q = {} if user["role"] == "admin" else {"uploadedBy": user["email"]}
    cur = get_db().uploads.find(q, {"logs": 0}).sort("uploadedAt", -1).limit(200)
    return [serialize_upload(u, with_logs=False) async for u in cur]


async def _get(upload_id: str, user) -> dict:
    try:
        u = await get_db().uploads.find_one({"_id": ObjectId(upload_id)})
    except InvalidId:
        u = None
    if not u or (user["role"] != "admin" and u["uploadedBy"] != user["email"]):
        raise HTTPException(404, "Upload not found")
    return u


@router.get("/{upload_id}")
async def get_upload(upload_id: str, user=Depends(require_uploader)):
    return serialize_upload(await _get(upload_id, user))


@router.delete("/{upload_id}", status_code=204)
async def delete_upload(upload_id: str, admin=Depends(require_admin)):
    u = await _get(upload_id, admin)
    m = get_module(u["module"])
    if m:
        await m.delete_upload_data(get_db(), get_storage(), upload_id)
    await get_db().uploads.delete_one({"_id": u["_id"]})
