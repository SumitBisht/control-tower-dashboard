import re
from typing import Literal

from pydantic import BaseModel, field_validator

Role = Literal["viewer", "uploader", "admin"]
Status = Literal["pending", "active", "disabled"]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _Email(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _v(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL.match(v):
            raise ValueError("invalid email")
        return v


class LoginIn(_Email):
    password: str


class RegisterIn(_Email):
    name: str
    password: str

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name required")
        return v


class UserCreateIn(RegisterIn):
    role: Role = "viewer"


class UserUpdateIn(BaseModel):
    name: str | None = None
    role: Role | None = None
    status: Status | None = None
    password: str | None = None


class WidgetSettingIn(BaseModel):
    visible: bool | None = None
    columns: dict[str, bool] | None = None
