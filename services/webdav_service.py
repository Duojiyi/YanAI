from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, build_opener

from services.config import config
from services.repositories.base import ImageRecordRepository, RepositoryProvider
from utils.timezone import china_now_text

ADMIN_CONFIG_KEY = "image_webdav_config"
USER_CONFIG_KEY = "webdav_config"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _now_text() -> str:
    return china_now_text()


def _normalize_path(value: object) -> str:
    parts = [
        part.strip()
        for part in _clean(value).replace("\\", "/").split("/")
        if part.strip() and part.strip() not in {".", ".."}
    ]
    return "/".join(parts)


def _normalize_config(raw: object, *, include_password: bool = False) -> dict[str, object]:
    data = dict(raw) if isinstance(raw, dict) else {}
    password = _clean(data.get("password"))
    result: dict[str, object] = {
        "enabled": _bool(data.get("enabled"), False),
        "url": _clean(data.get("url")).rstrip("/"),
        "username": _clean(data.get("username")),
        "root_path": _normalize_path(data.get("root_path")),
        "password_set": bool(password),
        "last_sync_at": _clean(data.get("last_sync_at")) or None,
        "last_sync_result": data.get("last_sync_result") if isinstance(data.get("last_sync_result"), dict) else None,
    }
    if include_password:
        result["password"] = password
    return result


def _merge_config(current: object, updates: dict[str, object]) -> dict[str, object]:
    existing = _normalize_config(current, include_password=True)
    next_config = dict(existing)
    for key in ("enabled", "url", "username", "root_path", "last_sync_at", "last_sync_result"):
        if key in updates:
            next_config[key] = updates.get(key)
    if "password" in updates and _clean(updates.get("password")):
        next_config["password"] = _clean(updates.get("password"))
    next_config["enabled"] = _bool(next_config.get("enabled"), False)
    next_config["url"] = _clean(next_config.get("url")).rstrip("/")
    next_config["username"] = _clean(next_config.get("username"))
    next_config["root_path"] = _normalize_path(next_config.get("root_path"))
    if next_config["enabled"] and not next_config["url"]:
        raise ValueError("webdav url is required")
    return _normalize_config(next_config, include_password=True)


def _admin_config(include_password: bool = False) -> dict[str, object]:
    return _normalize_config(config.data.get(ADMIN_CONFIG_KEY), include_password=include_password)


def _save_admin_config(updates: dict[str, object]) -> dict[str, object]:
    next_config = _merge_config(config.data.get(ADMIN_CONFIG_KEY), updates)
    config.data[ADMIN_CONFIG_KEY] = next_config
    config._save()
    return _normalize_config(next_config)


def _repository_provider() -> RepositoryProvider | None:
    get_provider = getattr(config, "get_repository_provider", None)
    if not callable(get_provider):
        return None
    provider = get_provider()
    return provider if isinstance(provider, RepositoryProvider) else None


def _load_users() -> tuple[list[dict[str, object]], Any]:
    provider = _repository_provider()
    if provider is not None:
        return provider.users.list(), provider.users
    storage = config.get_storage_backend()
    return storage.load_users(), storage


def _save_user(user: dict[str, object], source: Any, users: list[dict[str, object]]) -> None:
    if hasattr(source, "upsert"):
        source.upsert(user)
        return
    source.save_users(users)


def _user_config(user_id: str, *, include_password: bool = False) -> dict[str, object]:
    normalized_user_id = _clean(user_id)
    users, _ = _load_users()
    for user in users:
        if _clean(user.get("id")) == normalized_user_id:
            return _normalize_config(user.get(USER_CONFIG_KEY), include_password=include_password)
    return _normalize_config({})


def _save_user_config(user_id: str, updates: dict[str, object]) -> dict[str, object]:
    normalized_user_id = _clean(user_id)
    if not normalized_user_id:
        raise ValueError("user id is required")
    users, source = _load_users()
    for index, user in enumerate(users):
        if _clean(user.get("id")) != normalized_user_id:
            continue
        next_user = dict(user)
        next_user[USER_CONFIG_KEY] = _merge_config(user.get(USER_CONFIG_KEY), updates)
        users[index] = next_user
        _save_user(next_user, source, users)
        return _normalize_config(next_user[USER_CONFIG_KEY])
    raise ValueError("user not found")


def get_webdav_config(scope: str, *, user_id: str = "", include_password: bool = False) -> dict[str, object]:
    if scope == "user":
        return _user_config(user_id, include_password=include_password)
    if scope == "admin":
        return _admin_config(include_password=include_password)
    raise ValueError("invalid webdav scope")


def save_webdav_config(scope: str, updates: dict[str, object], *, user_id: str = "") -> dict[str, object]:
    if scope == "user":
        return _save_user_config(user_id, updates)
    if scope == "admin":
        return _save_admin_config(updates)
    raise ValueError("invalid webdav scope")


def _authorization_header(username: str, password: str) -> str | None:
    if not username and not password:
        return None
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request(method: str, url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> int:
    request = Request(url, data=data, headers=headers or {}, method=method)
    with build_opener().open(request, timeout=timeout) as response:
        return int(getattr(response, "status", response.getcode()))


def _split_remote_parts(value: str) -> list[str]:
    return [part for part in _normalize_path(value).split("/") if part]


def _join_remote_url(base_url: str, parts: list[str]) -> str:
    url = _clean(base_url).rstrip("/")
    for part in parts:
        url += "/" + quote(part, safe="")
    return url


def _remote_parts(remote_root: str, relative_path: Path) -> list[str]:
    return [*_split_remote_parts(remote_root), *[part for part in relative_path.as_posix().split("/") if part]]


def _ensure_remote_dirs(
    *,
    base_url: str,
    parts: list[str],
    headers: dict[str, str],
    timeout: int,
) -> None:
    current_parts: list[str] = []
    for part in parts:
        current_parts.append(part)
        directory_url = _join_remote_url(base_url, current_parts)
        try:
            _request("MKCOL", directory_url, headers=headers, timeout=timeout)
        except HTTPError as exc:
            if exc.code in {200, 201, 204, 301, 302, 405}:
                continue
            raise


def _local_image_path_from_url(url: str) -> Path | None:
    parsed_path = unquote(urlparse(_clean(url)).path)
    if not parsed_path.startswith("/images/"):
        return None
    relative_path = parsed_path.removeprefix("/images/").strip("/")
    if not relative_path:
        return None
    root = config.images_dir.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _relative_image_path(local_path: Path) -> Path:
    return local_path.resolve().relative_to(config.images_dir.resolve())


def _record_id(record: dict[str, object]) -> str:
    return _clean(record.get("record_id") or record.get("id"))


def _record_matches_filters(record: dict[str, object], filters: dict[str, object]) -> bool:
    created_at = _clean(record.get("created_at"))
    day = created_at[:10]
    owner_user_id = _clean(filters.get("owner_user_id"))
    channel = _clean(filters.get("channel"))
    request_id = _clean(filters.get("request_id"))
    start_date = _clean(filters.get("start_date"))
    end_date = _clean(filters.get("end_date"))
    record_ids = set(filters.get("record_ids", [])) if isinstance(filters.get("record_ids"), list) else set()
    if record_ids and _record_id(record) not in record_ids:
        return False
    if owner_user_id and _clean(record.get("owner_user_id")) != owner_user_id:
        return False
    if channel and _clean(record.get("channel")) != channel:
        return False
    if request_id and _clean(record.get("request_id")) != request_id:
        return False
    if start_date and day < start_date:
        return False
    if end_date and day > end_date:
        return False
    return True


def _image_record_source() -> ImageRecordRepository | Any:
    provider = _repository_provider()
    if provider is not None:
        return provider.image_records
    return config.get_storage_backend()


def _load_records(source: ImageRecordRepository | Any) -> list[dict[str, object]]:
    if isinstance(source, ImageRecordRepository):
        return source.list()
    return source.load_image_records()


def _save_records(source: ImageRecordRepository | Any, records: list[dict[str, object]], changed: list[dict[str, object]]) -> None:
    if isinstance(source, ImageRecordRepository):
        for record in changed:
            source.upsert(record)
        return
    source.save_image_records(records)


def _target_key(scope: str, user_id: str) -> str:
    return f"user:{user_id}" if scope == "user" else "admin"


def _mark_record_sync(
    record: dict[str, object],
    *,
    scope: str,
    user_id: str,
    status: str,
    remote_url: str = "",
    error: str = "",
) -> None:
    synced_at = _now_text()
    syncs = record.get("webdav_syncs")
    sync_map = dict(syncs) if isinstance(syncs, dict) else {}
    target = _target_key(scope, user_id)
    sync_map[target] = {
        "status": status,
        "url": remote_url,
        "error": error,
        "synced_at": synced_at,
    }
    record["webdav_syncs"] = sync_map
    record["webdav_status"] = status
    record["webdav_url"] = remote_url
    record["webdav_synced_at"] = synced_at
    if error:
        record["webdav_error"] = error
    elif "webdav_error" in record:
        record.pop("webdav_error", None)


def _upload_file(webdav_config: dict[str, object], local_path: Path) -> str:
    base_url = _clean(webdav_config.get("url")).rstrip("/")
    if not base_url:
        raise ValueError("webdav url is required")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("webdav url is invalid")

    relative_path = _relative_image_path(local_path)
    parts = _remote_parts(_clean(webdav_config.get("root_path")), relative_path)
    remote_url = _join_remote_url(base_url, parts)
    auth = _authorization_header(_clean(webdav_config.get("username")), _clean(webdav_config.get("password")))
    headers: dict[str, str] = {}
    if auth:
        headers["Authorization"] = auth
    _ensure_remote_dirs(
        base_url=base_url,
        parts=parts[:-1],
        headers=headers,
        timeout=30,
    )
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    put_headers = {**headers, "Content-Type": content_type}
    status = _request("PUT", remote_url, data=local_path.read_bytes(), headers=put_headers, timeout=60)
    if status not in {200, 201, 204}:
        raise RuntimeError(f"webdav put returned status {status}")
    return remote_url


def _sync_config_status(scope: str, user_id: str, result: dict[str, object]) -> None:
    summary = {
        "total": result.get("total", 0),
        "uploaded": result.get("uploaded", 0),
        "skipped": result.get("skipped", 0),
        "failed": result.get("failed", 0),
    }
    current = get_webdav_config(scope, user_id=user_id, include_password=True)
    current["last_sync_at"] = _now_text()
    current["last_sync_result"] = summary
    if scope == "admin":
        config.data[ADMIN_CONFIG_KEY] = current
        config._save()
    else:
        _save_user_config(user_id, current)


def sync_images_to_webdav(
    *,
    scope: str,
    identity: dict[str, object],
    filters: dict[str, object] | None = None,
) -> dict[str, object]:
    user_id = _clean(identity.get("id")) if scope == "user" else ""
    webdav_config = get_webdav_config(scope, user_id=user_id, include_password=True)
    if not _bool(webdav_config.get("enabled")):
        raise ValueError("webdav is not enabled")
    if not _clean(webdav_config.get("url")):
        raise ValueError("webdav url is required")

    normalized_filters = dict(filters or {})
    if scope == "user":
        normalized_filters["owner_user_id"] = user_id
    source = _image_record_source()
    try:
        records = _load_records(source)
    except Exception:
        records = []

    changed: list[dict[str, object]] = []
    result: dict[str, object] = {
        "scope": scope,
        "total": 0,
        "uploaded": 0,
        "skipped": 0,
        "failed": 0,
        "bytes": 0,
        "errors": [],
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not _record_matches_filters(record, normalized_filters):
            continue
        result["total"] = int(result["total"]) + 1
        local_path = _local_image_path_from_url(_clean(record.get("url")))
        if local_path is None:
            result["skipped"] = int(result["skipped"]) + 1
            continue
        if not local_path.is_file() or local_path.stat().st_size <= 0:
            result["skipped"] = int(result["skipped"]) + 1
            continue
        try:
            remote_url = _upload_file(webdav_config, local_path)
            next_record = dict(record)
            _mark_record_sync(next_record, scope=scope, user_id=user_id, status="synced", remote_url=remote_url)
            records[index] = next_record
            changed.append(next_record)
            result["uploaded"] = int(result["uploaded"]) + 1
            result["bytes"] = int(result["bytes"]) + local_path.stat().st_size
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            next_record = dict(record)
            error = str(exc)
            _mark_record_sync(next_record, scope=scope, user_id=user_id, status="failed", error=error)
            records[index] = next_record
            changed.append(next_record)
            result["failed"] = int(result["failed"]) + 1
            errors = result["errors"]
            if isinstance(errors, list) and len(errors) < 20:
                errors.append({
                    "id": _record_id(record),
                    "name": local_path.name,
                    "error": error,
                })

    if changed:
        _save_records(source, records, changed)
    _sync_config_status(scope, user_id, result)
    return result


def sync_created_records_to_webdav(identity: dict[str, object], records: list[dict[str, object]]) -> dict[str, object] | None:
    if not records:
        return None
    scope = "user" if _clean(identity.get("role")) == "user" else "admin"
    user_id = _clean(identity.get("id")) if scope == "user" else ""
    webdav_config = get_webdav_config(scope, user_id=user_id, include_password=True)
    if not _bool(webdav_config.get("enabled")):
        return None
    record_ids = [_record_id(record) for record in records if _record_id(record)]
    if not record_ids:
        return None
    try:
        return sync_images_to_webdav(scope=scope, identity=identity, filters={"record_ids": record_ids})
    except Exception:
        return None
