from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from pathlib import Path
import time

from services.storage.base import StorageBackend

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"
VERSION_FILE = BASE_DIR / "VERSION"


@dataclass(frozen=True)
class LoadedSettings:
    auth_key: str
    refresh_account_interval_minute: int


def _normalize_auth_key(value: object) -> str:
    return str(value or "").strip()


def _is_invalid_auth_key(value: object) -> bool:
    return _normalize_auth_key(value) == ""


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clean_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace(";", "\n").replace(",", "\n").splitlines()
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    seen: set[str] = set()
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip().lower().lstrip("@")
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _read_json_object(path: Path, *, name: str) -> dict[str, object]:
    if not path.exists():
        return {}
    if path.is_dir():
        print(
            f"Warning: {name} at '{path}' is a directory, ignoring it and falling back to other configuration sources.",
            file=sys.stderr,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_settings() -> LoadedSettings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_config = _read_json_object(CONFIG_FILE, name="config.json")
    auth_key = _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or raw_config.get("auth-key"))
    if _is_invalid_auth_key(auth_key):
        raise ValueError(
            "❌ auth-key 未设置！\n"
            "请在环境变量 CHATGPT2API_AUTH_KEY 中设置，或者在 config.json 中填写 auth-key。"
        )

    try:
        refresh_interval = int(raw_config.get("refresh_account_interval_minute", 5))
    except (TypeError, ValueError):
        refresh_interval = 5

    return LoadedSettings(
        auth_key=auth_key,
        refresh_account_interval_minute=refresh_interval,
    )


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._storage_backend: StorageBackend | None = None
        if _is_invalid_auth_key(self.auth_key):
            raise ValueError(
                "❌ auth-key 未设置！\n"
                "请按以下任意一种方式解决：\n"
                "1. 在 Render 的 Environment 变量中添加：\n"
                "   CHATGPT2API_AUTH_KEY = your_real_auth_key\n"
                "2. 或者在 config.json 中填写：\n"
                '   "auth-key": "your_real_auth_key"'
            )

    def _load(self) -> dict[str, object]:
        return _read_json_object(self.path, name="config.json")

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @property
    def auth_key(self) -> str:
        return _normalize_auth_key(os.getenv("CHATGPT2API_AUTH_KEY") or self.data.get("auth-key"))

    @property
    def accounts_file(self) -> Path:
        return DATA_DIR / "accounts.json"

    @property
    def refresh_account_interval_minute(self) -> int:
        try:
            return int(self.data.get("refresh_account_interval_minute", 5))
        except (TypeError, ValueError):
            return 5

    @property
    def image_retention_days(self) -> int:
        try:
            return max(1, int(self.data.get("image_retention_days", 30)))
        except (TypeError, ValueError):
            return 30

    @property
    def auto_remove_invalid_accounts(self) -> bool:
        return _bool(self.data.get("auto_remove_invalid_accounts"), False)

    @property
    def auto_remove_rate_limited_accounts(self) -> bool:
        return _bool(self.data.get("auto_remove_rate_limited_accounts"), False)

    @property
    def log_levels(self) -> list[str]:
        levels = self.data.get("log_levels")
        if not isinstance(levels, list):
            return []
        allowed = {"debug", "info", "warning", "error"}
        return [level for item in levels if (level := str(item or "").strip().lower()) in allowed]

    @property
    def allow_user_registration(self) -> bool:
        return _bool(self.data.get("allow_user_registration"), True)

    @property
    def new_user_initial_quota(self) -> int:
        try:
            return max(0, int(self.data.get("new_user_initial_quota", 0)))
        except (TypeError, ValueError):
            return 0

    @property
    def email_verification_enabled(self) -> bool:
        return _bool(self.data.get("email_verification_enabled"), False)

    @property
    def email_domain_whitelist_enabled(self) -> bool:
        return _bool(self.data.get("email_domain_whitelist_enabled"), False)

    @property
    def email_alias_restriction_enabled(self) -> bool:
        return _bool(self.data.get("email_alias_restriction_enabled"), False)

    @property
    def email_domain_whitelist(self) -> list[str]:
        return _clean_list(self.data.get("email_domain_whitelist"))

    @property
    def smtp_host(self) -> str:
        return str(os.getenv("CHATGPT2API_SMTP_HOST") or self.data.get("smtp_host") or "").strip()

    @property
    def smtp_port(self) -> int:
        try:
            return max(1, int(os.getenv("CHATGPT2API_SMTP_PORT") or self.data.get("smtp_port") or 587))
        except (TypeError, ValueError):
            return 587

    @property
    def smtp_username(self) -> str:
        return str(os.getenv("CHATGPT2API_SMTP_USERNAME") or self.data.get("smtp_username") or "").strip()

    @property
    def smtp_password(self) -> str:
        return str(os.getenv("CHATGPT2API_SMTP_PASSWORD") or self.data.get("smtp_password") or "").strip()

    @property
    def smtp_from_email(self) -> str:
        return str(os.getenv("CHATGPT2API_SMTP_FROM") or self.data.get("smtp_from_email") or self.smtp_username).strip()

    @property
    def smtp_use_ssl(self) -> bool:
        return _bool(self.data.get("smtp_use_ssl"), self.smtp_port == 465)

    @property
    def smtp_use_starttls(self) -> bool:
        return _bool(self.data.get("smtp_use_starttls"), not self.smtp_use_ssl)

    @property
    def smtp_force_auth_login(self) -> bool:
        return _bool(self.data.get("smtp_force_auth_login"), False)

    @property
    def linuxdo_oauth_enabled(self) -> bool:
        return _bool(self.data.get("linuxdo_oauth_enabled"), False)

    @property
    def linuxdo_client_id(self) -> str:
        return str(os.getenv("LINUX_DO_CLIENT_ID") or self.data.get("linuxdo_client_id") or "").strip()

    @property
    def linuxdo_client_secret(self) -> str:
        return str(os.getenv("LINUX_DO_CLIENT_SECRET") or self.data.get("linuxdo_client_secret") or "").strip()

    @property
    def linuxdo_minimum_trust_level(self) -> int:
        try:
            return max(0, min(4, int(self.data.get("linuxdo_minimum_trust_level", 0))))
        except (TypeError, ValueError):
            return 0

    @property
    def images_dir(self) -> Path:
        path = DATA_DIR / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def prompt_assets_dir(self) -> Path:
        path = DATA_DIR / "prompt-assets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup_old_images(self) -> int:
        cutoff = time.time() - self.image_retention_days * 86400
        removed = 0
        for path in self.images_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        for path in sorted((p for p in self.images_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        return removed

    @property
    def base_url(self) -> str:
        return str(
            os.getenv("CHATGPT2API_BASE_URL")
            or self.data.get("base_url")
            or ""
        ).strip().rstrip("/")

    @property
    def image_model_mappings(self) -> dict[str, str]:
        defaults = {
            "gpt-image-2": "gpt-5-5",
            "codex-gpt-image-2": "codex-gpt-image-2",
        }
        raw = self.data.get("image_model_mappings")
        if not isinstance(raw, dict):
            return defaults
        mappings = dict(defaults)
        for key, value in raw.items():
            source_model = str(key or "").strip()
            target_model = str(value or "").strip()
            if source_model and target_model:
                mappings[source_model] = target_model
        return mappings

    @property
    def app_version(self) -> str:
        try:
            value = VERSION_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0"
        return value or "0.0.0"

    def get(self) -> dict[str, object]:
        data = dict(self.data)
        data["refresh_account_interval_minute"] = self.refresh_account_interval_minute
        data["image_retention_days"] = self.image_retention_days
        data["auto_remove_invalid_accounts"] = self.auto_remove_invalid_accounts
        data["auto_remove_rate_limited_accounts"] = self.auto_remove_rate_limited_accounts
        data["log_levels"] = self.log_levels
        data["allow_user_registration"] = self.allow_user_registration
        data["new_user_initial_quota"] = self.new_user_initial_quota
        data["email_verification_enabled"] = self.email_verification_enabled
        data["email_domain_whitelist_enabled"] = self.email_domain_whitelist_enabled
        data["email_alias_restriction_enabled"] = self.email_alias_restriction_enabled
        data["email_domain_whitelist"] = self.email_domain_whitelist
        data["smtp_host"] = self.smtp_host
        data["smtp_port"] = self.smtp_port
        data["smtp_username"] = self.smtp_username
        data["smtp_from_email"] = self.smtp_from_email
        data["smtp_use_ssl"] = self.smtp_use_ssl
        data["smtp_use_starttls"] = self.smtp_use_starttls
        data["smtp_force_auth_login"] = self.smtp_force_auth_login
        data["smtp_password_set"] = bool(self.smtp_password)
        data["linuxdo_oauth_enabled"] = self.linuxdo_oauth_enabled
        data["linuxdo_client_id"] = self.linuxdo_client_id
        data["linuxdo_minimum_trust_level"] = self.linuxdo_minimum_trust_level
        data["linuxdo_client_secret_set"] = bool(self.linuxdo_client_secret)
        data["image_model_mappings"] = self.image_model_mappings
        data.pop("auth-key", None)
        data.pop("smtp_password", None)
        data.pop("linuxdo_client_secret", None)
        return data

    def get_proxy_settings(self) -> str:
        return str(self.data.get("proxy") or "").strip()

    def update(self, data: dict[str, object]) -> dict[str, object]:
        updates = dict(data or {})
        for transient_key in ("smtp_password_set", "linuxdo_client_secret_set"):
            updates.pop(transient_key, None)
        for secret_key in ("smtp_password", "linuxdo_client_secret"):
            if secret_key in updates and not str(updates.get(secret_key) or "").strip():
                updates.pop(secret_key, None)
        if "email_domain_whitelist" in updates:
            updates["email_domain_whitelist"] = _clean_list(updates.get("email_domain_whitelist"))
        next_data = dict(self.data)
        next_data.update(updates)
        self.data = next_data
        self._save()
        return self.get()

    def get_storage_backend(self) -> StorageBackend:
        """获取存储后端实例（单例）"""
        if self._storage_backend is None:
            from services.storage.factory import create_storage_backend
            self._storage_backend = create_storage_backend(DATA_DIR)
        return self._storage_backend


config = ConfigStore(CONFIG_FILE)
