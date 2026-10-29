"""File storage abstraction: local disk for dev, S3 for AWS. Same interface for both."""
from pathlib import Path
from typing import Protocol

from .config import get_settings


class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def save_file(self, key: str, path: str, content_type: str | None = None) -> None: ...
    def load(self, key: str) -> bytes: ...
    def delete_prefix(self, prefix: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def save(self, key, data, content_type=None):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def save_file(self, key, path, content_type=None):
        import shutil

        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, p)

    def load(self, key):
        return self._path(key).read_bytes()

    def delete_prefix(self, prefix):
        import shutil

        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()


class S3Storage:
    def __init__(self, bucket: str):
        import boto3

        self.bucket, self.s3 = bucket, boto3.client("s3")

    def save(self, key, data, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def save_file(self, key, path, content_type=None):
        extra = {"ExtraArgs": {"ContentType": content_type}} if content_type else {}
        self.s3.upload_file(path, self.bucket, key, **extra)

    def load(self, key):
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete_prefix(self, prefix):
        pager = self.s3.get_paginator("list_objects_v2")
        for page in pager.paginate(Bucket=self.bucket, Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objs})


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage(s.s3_bucket) if s.storage_backend == "s3" else LocalStorage(s.storage_local_dir)
    return _storage
