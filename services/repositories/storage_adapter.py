from __future__ import annotations

from typing import Any

from services.repositories.base import RepositoryProvider
from services.storage.base import StorageBackend


class RepositoryStorageAdapter(StorageBackend):
    """Compatibility adapter that exposes repositories as the legacy storage API."""

    def __init__(self, repositories: RepositoryProvider):
        self.repositories = repositories

    def load_accounts(self) -> list[dict[str, Any]]:
        return self.repositories.accounts.list()

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.repositories.accounts.replace_all(accounts)

    def load_auth_keys(self) -> list[dict[str, Any]]:
        return self.repositories.auth_keys.list()

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        self.repositories.auth_keys.replace_all(auth_keys)

    def load_users(self) -> list[dict[str, Any]]:
        return self.repositories.users.list()

    def save_users(self, users: list[dict[str, Any]]) -> None:
        self.repositories.users.replace_all(users)

    def load_sessions(self) -> list[dict[str, Any]]:
        return self.repositories.sessions.list()

    def save_sessions(self, sessions: list[dict[str, Any]]) -> None:
        self.repositories.sessions.replace_all(sessions)

    def load_redeem_codes(self) -> list[dict[str, Any]]:
        return self.repositories.redeem_codes.list()

    def save_redeem_codes(self, redeem_codes: list[dict[str, Any]]) -> None:
        self.repositories.redeem_codes.replace_all(redeem_codes)

    def load_channels(self) -> list[dict[str, Any]]:
        return self.repositories.channels.list()

    def save_channels(self, channels: list[dict[str, Any]]) -> None:
        self.repositories.channels.replace_all(channels)

    def load_prompt_library(self) -> list[dict[str, Any]]:
        return self.repositories.prompts.list()

    def save_prompt_library(self, prompts: list[dict[str, Any]]) -> None:
        self.repositories.prompts.replace_all(prompts)

    def load_image_records(self) -> list[dict[str, Any]]:
        return self.repositories.image_records.list()

    def save_image_records(self, image_records: list[dict[str, Any]]) -> None:
        self.repositories.image_records.replace_all(image_records)

    def health_check(self) -> dict[str, Any]:
        return self.repositories.health_check()

    def get_backend_info(self) -> dict[str, Any]:
        return self.repositories.get_backend_info()
