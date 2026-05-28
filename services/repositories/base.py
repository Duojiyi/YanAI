from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RepositoryError(RuntimeError):
    """Base repository error."""


class RepositoryValidationError(RepositoryError):
    """Raised when repository input would corrupt a dataset."""


class DatasetRepository(ABC):
    """Repository interface for one logical dataset."""

    dataset_name: str
    primary_key: str
    unique_keys: tuple[str, ...] = ()

    @abstractmethod
    def list(self) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def replace_all(self, items: list[dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def upsert(self, item: dict[str, Any]) -> None:
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

    @abstractmethod
    def key_set(self) -> set[str]:
        pass


class AccountRepository(DatasetRepository):
    pass


class AuthKeyRepository(DatasetRepository):
    pass


class UserRepository(DatasetRepository):
    pass


class SessionRepository(DatasetRepository):
    pass


class RedeemCodeRepository(DatasetRepository):
    pass


class ChannelRepository(DatasetRepository):
    pass


class PromptRepository(DatasetRepository):
    pass


class ImageRecordRepository(DatasetRepository):
    pass


class SystemConfigRepository(ABC):
    """Configuration repository boundary for future database-backed settings."""

    @abstractmethod
    def list_settings(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_setting(self, key: str, default: Any = None) -> Any:
        pass

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        pass

    @abstractmethod
    def delete_setting(self, key: str) -> bool:
        pass


class RepositoryProvider(ABC):
    @property
    @abstractmethod
    def accounts(self) -> AccountRepository:
        pass

    @property
    @abstractmethod
    def auth_keys(self) -> AuthKeyRepository:
        pass

    @property
    @abstractmethod
    def users(self) -> UserRepository:
        pass

    @property
    @abstractmethod
    def sessions(self) -> SessionRepository:
        pass

    @property
    @abstractmethod
    def redeem_codes(self) -> RedeemCodeRepository:
        pass

    @property
    @abstractmethod
    def channels(self) -> ChannelRepository:
        pass

    @property
    @abstractmethod
    def prompts(self) -> PromptRepository:
        pass

    @property
    @abstractmethod
    def image_records(self) -> ImageRecordRepository:
        pass

    @property
    @abstractmethod
    def system_config(self) -> SystemConfigRepository:
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_backend_info(self) -> dict[str, Any]:
        pass
