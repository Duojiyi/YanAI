from __future__ import annotations

from pathlib import Path


def create_storage_backend(data_dir: Path):
    from services.storage.factory import create_storage_backend as _create_storage_backend

    return _create_storage_backend(data_dir)

__all__ = ["create_storage_backend"]
