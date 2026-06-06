from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


def create_storage_backend(data_dir: Path, settings: Mapping[str, object] | None = None):
    from services.storage.factory import create_storage_backend as _create_storage_backend

    return _create_storage_backend(data_dir, settings)

__all__ = ["create_storage_backend"]
