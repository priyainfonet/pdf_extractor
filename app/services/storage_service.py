"""
Storage abstraction. Every part of the app that needs to read/write a
file goes through StorageService — never through open()/os.path directly.
That's what makes swapping local disk for S3 later a one-file change
instead of a grep-and-replace across the codebase.

Only a local filesystem backend is implemented right now (STORAGE_TYPE=local).
To add S3 later: implement S3StorageService with the same four methods,
matching this same interface, and flip STORAGE_TYPE=s3 in .env — nothing
in app/api or app/services/pdf_service.py needs to change.
"""

import os
import shutil
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional

from app.core.config import settings


class StorageService(ABC):
    @abstractmethod
    def save_file(self, storage_key: str, file_obj: BinaryIO) -> None:
        """Writes file_obj's contents to storage_key."""

    @abstractmethod
    def get_file_path(self, storage_key: str) -> str:
        """Returns a local filesystem path usable to read the file.
        For local storage this is direct. For a future S3 backend this
        would download to a temp file and return that path."""

    @abstractmethod
    def delete_file(self, storage_key: str) -> None:
        """Deletes the file at storage_key. No-op if it doesn't exist."""

    @abstractmethod
    def file_exists(self, storage_key: str) -> bool:
        ...

    @abstractmethod
    def generate_download_url(self, storage_key: str) -> Optional[str]:
        """Returns a directly-downloadable URL if the backend supports one
        (e.g. an S3 presigned URL). Returns None for local storage — callers
        fall back to streaming the file through our own API endpoint instead."""


class LocalStorageService(StorageService):
    def __init__(self, base_path: str):
        self.base_path = os.path.abspath(base_path)

    def _resolve(self, storage_key: str) -> str:
        # storage_key is always server-generated (see app/utils/filenames.py),
        # never derived from user input, so there's no path-traversal risk here.
        path = os.path.join(self.base_path, storage_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def save_file(self, storage_key: str, file_obj: BinaryIO) -> None:
        path = self._resolve(storage_key)
        with open(path, "wb") as out:
            shutil.copyfileobj(file_obj, out)

    def get_file_path(self, storage_key: str) -> str:
        return self._resolve(storage_key)

    def delete_file(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        if os.path.exists(path):
            os.remove(path)

    def file_exists(self, storage_key: str) -> bool:
        return os.path.exists(self._resolve(storage_key))

    def generate_download_url(self, storage_key: str) -> Optional[str]:
        return None  # local files are served through our own download endpoint


def get_storage_service() -> StorageService:
    if settings.STORAGE_TYPE == "local":
        return LocalStorageService(settings.STORAGE_PATH)
    raise NotImplementedError(
        f"Storage backend '{settings.STORAGE_TYPE}' isn't implemented yet. "
        "Add an S3StorageService(StorageService) subclass in this file and register it here."
    )


# Singleton — the whole app shares one instance, matching how a real S3
# client (with its own connection pool) would typically be used.
storage_service = get_storage_service()
