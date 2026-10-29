"""Generic upload pipeline: receive -> validate -> parse (pure) -> duplicate check -> persist -> log.

Uploads are processed in the background: POST /uploads returns immediately with status PROCESSING and the client
polls GET /uploads/{id}. (Reports with embedded photos can be 100 MB+; this keeps the request short.)

Graceful termination guarantees:
  * every failure path ends with the upload record in a terminal state (FAILED / SUCCESS*) and a readable log;
  * parsing never writes; persistence is rolled back on any exception, so a failed upload leaves no partial data;
  * unexpected exceptions are logged server-side and surfaced to the user as a generic message (no stack traces);
  * uploads orphaned by a server restart are marked FAILED on the next start (see fail_interrupted_uploads).
"""
import asyncio
import logging
import os
import zipfile
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from .core.config import get_settings
from .core.storage import get_storage
from .modules.base import Issue, ReportModule, UploadContext

log = logging.getLogger("uploads")
_tasks: set[asyncio.Task] = set()  # keep references so background tasks are not garbage collected


def _validate_file(module: ReportModule, filename: str, path: str) -> list[Issue]:
    s = get_settings()
    issues = []
    if not filename.lower().endswith(module.file_extensions):
        issues.append(Issue("ERROR", "BAD_EXTENSION", f"Only {', '.join(module.file_extensions)} files are accepted (got '{filename}')."))
        return issues
    if os.path.getsize(path) == 0:
        return [Issue("ERROR", "EMPTY_FILE", "The uploaded file is empty.")]
    if filename.lower().endswith(".docx"):
        try:
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
                if sum(i.file_size for i in infos) > s.max_uncompressed_mb * 1024 * 1024 or len(infos) > 10000:
                    issues.append(Issue("ERROR", "ARCHIVE_TOO_LARGE", "The document expands to an unreasonable size and was rejected."))
                if "word/document.xml" not in z.namelist():
                    issues.append(Issue("ERROR", "NOT_DOCX", "The file is not a Word (.docx) document."))
        except zipfile.BadZipFile:
            issues.append(Issue("ERROR", "NOT_DOCX", "The file is not a valid .docx (corrupted, password-protected, or a legacy .doc renamed to .docx)."))
    return issues


async def create_upload(db, module: ReportModule, user: dict, filename: str, size: int, file_hash: str, options: dict) -> dict:
    doc = {"module": module.key, "fileName": filename, "fileSize": size, "fileHash": file_hash, "uploadedBy": user["email"],
           "uploadedAt": datetime.now(timezone.utc), "status": "PROCESSING", "options": options, "summary": None,
           "logs": [Issue("INFO", "RECEIVED", f"Received '{filename}' ({size / 1024 / 1024:.1f} MB). Processing started.").to_log()]}
    doc["_id"] = (await db.uploads.insert_one(doc)).inserted_id
    return doc


def start_processing(db, module: ReportModule, upload: dict, user: dict, path: str) -> None:
    """Fire-and-forget; the temp file at `path` is removed when processing ends."""
    task = asyncio.create_task(process_upload(db, module, upload, user, path))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def process_upload(db, module: ReportModule, upload: dict, user: dict, path: str) -> None:
    s = get_settings()
    upload_id = str(upload["_id"])
    ctx = UploadContext(upload_id, upload["fileName"], upload["fileHash"], user["email"], upload["options"], path)
    storage = get_storage()
    issues: list[Issue] = [Issue(i["level"], i["code"], i["message"]) for i in upload["logs"]]
    status, summary, persisted = "FAILED", None, False
    try:
        issues += _validate_file(module, upload["fileName"], path)
        if not any(i.level == "ERROR" for i in issues):
            try:
                parsed = await asyncio.wait_for(asyncio.to_thread(module.parse, path, ctx), timeout=s.parse_timeout_seconds)
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
                            persisted = True  # from here a failure must roll back
                            summary = await module.persist(db, storage, parsed.data, ctx)
                        except Exception:  # noqa: BLE001
                            log.exception("persist failed for upload %s", upload_id)
                            issues.append(Issue("ERROR", "SAVE_FAILED", "Saving the data failed; the upload was rolled back and nothing was stored. Please retry."))
                            await _rollback(db, module, storage, upload_id)
                            persisted = False
        errors = [i for i in issues if i.level == "ERROR"]
        if errors:
            status = "FAILED"
            issues.append(Issue("ERROR", "ABORTED", f"Upload aborted: {len(errors)} error(s). No data was saved."))
        else:
            status = "SUCCESS_WITH_WARNINGS" if any(i.level == "WARNING" for i in issues) else "SUCCESS"
            issues.append(Issue("INFO", "DONE", "Upload completed and the dashboard is updated."))
    except Exception:  # noqa: BLE001  (last resort: never leave the record stuck in PROCESSING)
        log.exception("unexpected failure for upload %s", upload_id)
        if persisted:
            await _rollback(db, module, storage, upload_id)
        issues.append(Issue("ERROR", "UNEXPECTED", "An unexpected error occurred. Nothing was saved. Please try again or contact an administrator."))
        status, summary = "FAILED", None
    finally:
        try:
            await db.uploads.update_one({"_id": upload["_id"]}, {"$set": {
                "status": status, "summary": summary, "finishedAt": datetime.now(timezone.utc),
                "logs": [i.to_log() for i in issues]}})
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


async def fail_interrupted_uploads(db) -> None:
    """On startup: uploads still PROCESSING were interrupted by a restart/crash."""
    log_entry = Issue("ERROR", "INTERRUPTED", "Processing was interrupted by a server restart. Nothing was saved; please upload again.").to_log()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=get_settings().parse_timeout_seconds + 300)  # other instances may be mid-upload
    res = await db.uploads.update_many({"status": "PROCESSING", "uploadedAt": {"$lt": cutoff}}, {"$set": {"status": "FAILED", "finishedAt": datetime.now(timezone.utc)},
                                                                   "$push": {"logs": log_entry}})
    if res.modified_count:
        log.warning("marked %d interrupted upload(s) as FAILED", res.modified_count)


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
