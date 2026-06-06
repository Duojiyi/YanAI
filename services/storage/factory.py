from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote

from services.storage.base import StorageBackend
from services.storage.database_storage import DatabaseStorageBackend
from services.storage.git_storage import GitStorageBackend
from services.storage.json_storage import JSONStorageBackend


def create_storage_backend(data_dir: Path, settings: Mapping[str, object] | None = None) -> StorageBackend:
    """
    根据环境变量或 config.json 创建存储后端
    
    环境变量优先；未设置时读取项目根目录 config.json：
    - STORAGE_BACKEND: json|sqlite|postgres|git (默认 json)
    - DATABASE_URL: 数据库连接字符串 (用于 sqlite/postgres)
    - GIT_REPO_URL: Git 仓库地址 (用于 git)
    - GIT_TOKEN: Git 访问令牌 (用于 git)
    - GIT_BRANCH: Git 分支 (默认 main)
    - GIT_FILE_PATH: Git 仓库中的文件路径 (默认 accounts.json)
    - GIT_*_FILE_PATH: Git 仓库中各数据集的文件路径
    """
    resolved_settings = settings if settings is not None else _load_config_settings(data_dir)
    backend_type = _get_setting("STORAGE_BACKEND", "json", resolved_settings).lower()
    
    print(f"[storage] Initializing storage backend: {backend_type}")
    
    if backend_type == "json":
        # 本地 JSON 文件存储
        file_path = data_dir / "accounts.json"
        auth_keys_path = data_dir / "auth_keys.json"
        print(f"[storage] Using JSON storage: {file_path}")
        return JSONStorageBackend(file_path, auth_keys_path)
    
    elif backend_type in ("sqlite", "postgres", "postgresql", "mysql", "database"):
        # 数据库存储
        database_url = _get_setting("DATABASE_URL", "", resolved_settings)
        
        if not database_url:
            # 如果没有指定 DATABASE_URL，使用本地 SQLite
            database_url = f"sqlite:///{data_dir / 'accounts.db'}"
            print(f"[storage] No DATABASE_URL provided, using local SQLite: {database_url}")
        else:
            database_url = _normalize_database_url(database_url)
            print(f"[storage] Using database storage: {_mask_password(database_url)}")
        
        return DatabaseStorageBackend(database_url)
    
    elif backend_type == "git":
        # Git 仓库存储
        repo_url = _get_setting("GIT_REPO_URL", "", resolved_settings)
        token = _get_setting("GIT_TOKEN", "", resolved_settings)
        branch = _get_setting("GIT_BRANCH", "main", resolved_settings)
        file_path = _get_setting("GIT_FILE_PATH", "accounts.json", resolved_settings)
        auth_keys_file_path = _get_setting("GIT_AUTH_KEYS_FILE_PATH", "auth_keys.json", resolved_settings)
        users_file_path = _get_setting("GIT_USERS_FILE_PATH", "users.json", resolved_settings)
        sessions_file_path = _get_setting("GIT_SESSIONS_FILE_PATH", "sessions.json", resolved_settings)
        redeem_codes_file_path = _get_setting("GIT_REDEEM_CODES_FILE_PATH", "redeem_codes.json", resolved_settings)
        channels_file_path = _get_setting("GIT_CHANNELS_FILE_PATH", "channels.json", resolved_settings)
        prompt_library_file_path = _get_setting("GIT_PROMPT_LIBRARY_FILE_PATH", "prompt_library.json", resolved_settings)
        image_records_file_path = _get_setting("GIT_IMAGE_RECORDS_FILE_PATH", "image_records.json", resolved_settings)
        
        if not repo_url:
            raise ValueError(
                "GIT_REPO_URL is required when using git storage backend. "
                "Please set GIT_REPO_URL environment variable."
            )
        
        print(f"[storage] Using Git storage: {_mask_token(repo_url)}, branch: {branch}, file: {file_path}")
        
        cache_dir = data_dir / "git_cache"
        return GitStorageBackend(
            repo_url=repo_url,
            token=token,
            branch=branch,
            file_path=file_path,
            auth_keys_file_path=auth_keys_file_path,
            users_file_path=users_file_path,
            sessions_file_path=sessions_file_path,
            redeem_codes_file_path=redeem_codes_file_path,
            channels_file_path=channels_file_path,
            prompt_library_file_path=prompt_library_file_path,
            image_records_file_path=image_records_file_path,
            local_cache_dir=cache_dir,
        )
    
    else:
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            f"Supported backends: json, sqlite, postgres, git"
        )


def _mask_password(url: str) -> str:
    """隐藏数据库连接字符串中的密码"""
    if "://" not in url:
        return url
    try:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host = rest.split("@", 1)
            if ":" in credentials:
                username, _ = credentials.split(":", 1)
                return f"{protocol}://{username}:****@{host}"
        return url
    except Exception:
        return url


def _load_config_settings(data_dir: Path) -> dict[str, object]:
    config_path = data_dir.resolve().parent / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_setting(name: str, default: str, settings: Mapping[str, object]) -> str:
    env_value = os.getenv(name)
    if env_value is not None and env_value.strip():
        return _strip_wrapping_quotes(env_value)

    value = _lookup_setting(settings, name, default)
    return _strip_wrapping_quotes(str(default if value is None else value))


def _lookup_setting(settings: Mapping[str, object], name: str, default: str) -> object:
    if name in settings:
        return settings[name]

    normalized_name = name.lower()
    for key, value in settings.items():
        if str(key).lower() == normalized_name:
            return value
    return default


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def _normalize_database_url(url: str) -> str:
    """URL-encode user info so raw password characters do not break SQLAlchemy parsing."""
    url = _strip_wrapping_quotes(url)
    if "://" not in url or "@" not in url:
        return url

    protocol, rest = url.split("://", 1)
    if protocol.startswith("sqlite") or rest.startswith("/"):
        return url

    authority_end = min(
        [index for marker in ("/", "?", "#") if (index := rest.find(marker)) != -1],
        default=len(rest),
    )
    authority = rest[:authority_end]
    suffix = rest[authority_end:]
    if "@" not in authority:
        return url

    credentials, host = authority.rsplit("@", 1)
    if not credentials:
        return url

    if ":" in credentials:
        username, password = credentials.split(":", 1)
        encoded_credentials = f"{quote(unquote(username), safe='')}:{quote(unquote(password), safe='')}"
    else:
        encoded_credentials = quote(unquote(credentials), safe="")

    return f"{protocol}://{encoded_credentials}@{host}{suffix}"


def _mask_token(url: str) -> str:
    """隐藏 URL 中的 token"""
    if "@" in url and "://" in url:
        protocol, rest = url.split("://", 1)
        if "@" in rest:
            _, host = rest.split("@", 1)
            return f"{protocol}://****@{host}"
    return url
