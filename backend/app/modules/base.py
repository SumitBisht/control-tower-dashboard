"""Extension point: every report type (container loading, factory audit, ...) is a ReportModule.

To add a new module: create app/modules/<name>/, subclass ReportModule, register it in registry.py.
The upload pipeline, widget visibility and column settings work for any registered module.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter


@dataclass
class Issue:
    level: str  # INFO | WARNING | ERROR
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_log(self) -> dict:
        return {"ts": datetime.now(timezone.utc), "level": self.level, "code": self.code,
                "message": self.message, "context": self.context}


@dataclass
class ParseResult:
    data: Any = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def ok(self) -> bool:
        return not self.errors and self.data is not None


@dataclass
class UploadContext:
    upload_id: str
    filename: str
    file_hash: str
    user_email: str
    options: dict[str, Any]
    path: str = ""  # temp file on local disk holding the uploaded document


@dataclass
class Column:
    key: str
    label: str


@dataclass
class WidgetDef:
    key: str
    title: str
    kind: str  # kpi | chart | table | checklist - frontend maps kind -> component
    columns: list[Column] = field(default_factory=list)


class ReportModule(ABC):
    key: str
    title: str
    file_extensions: tuple[str, ...] = (".docx",)
    widgets: list[WidgetDef]

    @abstractmethod
    def parse(self, source: "str | bytes", ctx: UploadContext) -> ParseResult:
        """Pure, synchronous parse. Must never write anything. Collect ALL issues rather than raising."""

    @abstractmethod
    async def check_duplicates(self, db, parsed: Any, ctx: UploadContext) -> list[Issue]: ...

    @abstractmethod
    async def persist(self, db, storage, parsed: Any, ctx: UploadContext) -> dict:
        """Write parsed data. Return a summary dict. May raise; the pipeline rolls back via delete_upload_data."""

    @abstractmethod
    async def delete_upload_data(self, db, storage, upload_id: str) -> None: ...

    @abstractmethod
    def router(self) -> APIRouter: ...

    async def ensure_indexes(self, db) -> None:
        return None
