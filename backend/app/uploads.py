"""Generic upload pipeline: validate -> parse (pure) -> duplicate check -> persist -> log.

Graceful termination guarantees:
  * every failure path ends with the upload record in a terminal state (FAILED / SUCCESS*) and a readable log;
  * parsing never writes; persistence is rolled back on any exception, so a failed upload leaves no partial data;
  * unexpected exceptions are logged server-side and surfaced to the user as a generic message (no stack traces).
"""
import asyncio
import hashlib
import io
import logging
import zipfile
from datetime import datetime, timezone

from bson import ObjectId

from .core.config import get_settings
from .core.storage import get_storage
from .modules.base import Issue, ReportModule, UploadContext

log = logging.getLogger("uploads")


def _validate_file(module: ReportModule, filename: str, data: bytes) -> list[Issue]:
    s = get_settings()
    issues = []
    if not filename.lower().endswith(module.file_extensions):
        issues.append(Issue("ERROR", "BAD_EXTENSION", f"Only {', '.join(module.file_extensions)} files are accepted (got '{filename}')."))
    if not data:
        issues.append(Issue("ERROR", "EMPTY_FILE", "The uploaded file is empty."))
    if issues:
        return issues
    if filename.lower().endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = z.infolist()
                if sum(i.file_size for i in infos) > s.max_uncompressed_mb * 1024 * 1024 or len(infos) > 10000:
                    issues.append(Issue("ERROR", "ARCHIVE_TOO_LARGE", "The document expands to an unreasonable size and was rejected."))
                if "word/document.xml" not in z.namelist():
                    issues.append(Issue("ERROR", "NOT_DOCX", "The file is not a Word (.docx) document."))
        except zipfile.BadZipFile:
            issues.append(Issue("ERROR", "NOT_DOCX", "The file is not a valid .docx (corrupted, password-protected, or a legacy .doc renamed to .docx)."))
    return issues


async def process_upload(db, module: ReportModule, user: dict, filename: str, data: bytes, options: dict) -> dict:
    s = get_settings()
    now = datetime.now(timezone.utc)
    file_hash = hashlib.sha256(data).hexdigest()
    upload = {"module": module.key, "fileName": filename, "fileSize": len(data), "fileHash": file_hash,
              "uploadedBy": user["email"], "uploadedAt": now, "status": "PROCESSING", "options": options, "logs": [], "summary": None}
    upload_id = str((await db.uploads.insert_one(upload)).inserted_id)
    upload["_id"] = ObjectId(upload_id)
    ctx = UploadContext(upload_id, filename, file_hash, user["email"], options)
    storage = get_storage()
    issues: list[Issue] = [Issue("INFO", "RECEIVED", f"Received '{filename}' ({len(data) / 1024:.0f} KB).")]
    status, summary, persisted = "FAILED", None, False
    try:
        issues += _validate_file(module, filename, data)
        if not any(i.level == "ERROR" for i in issues):
            try:
                parsed = await asyncio.wait_for(asyncio.to_thread(module.parse, data, ctx), timeout=s.parse_timeout_seconds)
            except asyncio.TimeoutError:
                issues.append(Issue("ERROR", "PARSE_TIMEOUT", f"Processing took longer than {s.parse_timeout_seconds}s and was stopped."))
                parsed = None
            except Exception:  # noqa: BLE001
                log.exception("parser crashed for upload %s", upload_id)
                issues.append(Issue("ERROR", "PARSE_CRASH", "The document structure is not what the template expects, so it could not be read. "
                                    "Make sure it was created from the official DSR template."))
                parsed = None
            if parsed is not None:
                issues += parsed.issues
                if parsed.ok:
                    issues += await module.check_duplicates(db, parsed.data, ctx)
                    if not any(i.level == "ERROR" for i in issues):
                        try:
                            summary = await module.persist(db, storage, parsed.data, ctx)
                            persisted = True
                        except Exception:  # noqa: BLE001
                            log.exception("persist failed for upload %s", upload_id)
                            issues.append(Issue("ERROR", "SAVE_FAILED", "Saving the data failed; the upload was rolled back and nothing was stored. Please retry."))
                            await _rollback(db, module, storage, upload_id)
        errors = [i for i in issues if i.level == "ERROR"]
        if errors:
            status = "FAILED"
            issues.append(Issue("ERROR", "ABORTED", f"Upload aborted: {len(errors)} error(s). No data was saved."))
        else:
            status = "SUCCESS_WITH_WARNINGS" if any(i.level == "WARNING" for i in issues) else "SUCCESS"
            issues.append(Issue("INFO", "DONE", "Upload completed and the dashboard is updated."))
    except Exception:  # noqa: BLE001  (last-resort: never leave the record stuck in PROCESSING)
        log.exception("unexpected failure for upload %s", upload_id)
        if persisted:
            await _rollback(db, module, storage, upload_id)
        issues.append(Issue("ERROR", "UNEXPECTED", "An unexpected error occurred. Nothing was saved. Please try again or contact an administrator."))
        status, summary = "FAILED", None
    finally:
        await db.uploads.update_one({"_id": upload["_id"]}, {"$set": {
            "status": status, "summary": summary, "finishedAt": datetime.now(timezone.utc),
            "logs": [i.to_log() for i in issues]}})
    return serialize_upload(await db.uploads.find_one({"_id": upload["_id"]}))


async def _rollback(db, module, storage, upload_id: str) -> None:
    try:
        await module.delete_upload_data(db, storage, upload_id)
    except Exception:  # noqa: BLE001
        log.exception("rollback failed for upload %s", upload_id)


def serialize_upload(u: dict, with_logs: bool = True) -> dict:
    out = {"id": str(u["_id"]), **{k: u.get(k) for k in ("module", "fileName", "fileSize", "uploadedBy", "uploadedAt", "finishedAt", "status", "summary", "options")}}
    logs = u.get("logs", [])
    out["counts"] = {lvl: sum(1 for entry in logs if entry["level"] == lvl) for lvl in ("ERROR", "WARNING", "INFO")}
    if with_logs:
        out["logs"] = logs
    return out
