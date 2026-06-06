from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

from services.repositories.sqlalchemy import (
    AccountRow as AccountModel,
    AuditLogRow as AuditLogModel,
    AuthKeyRow as AuthKeyModel,
    Base,
    ChannelRow as ChannelModel,
    ImageRecordRow as ImageRecordModel,
    PromptLibraryRow as PromptLibraryItemModel,
    QuotaReservationRow as QuotaReservationModel,
    RedeemCodeRow as RedeemCodeModel,
    SQLAlchemyRepositoryProvider,
    SessionRow as SessionModel,
    SystemLogRow as SystemLogModel,
    SystemSettingRow as SystemSettingModel,
    UserRow as UserModel,
)
from services.repositories.storage_adapter import RepositoryStorageAdapter


class DatabaseStorageBackend(RepositoryStorageAdapter):
    """Database storage backend backed by split repositories."""

    def __init__(self, database_url: str):
        ensure_database_exists(database_url)
        self.database_url = database_url
        self.repository_provider = SQLAlchemyRepositoryProvider(database_url)
        self.engine = self.repository_provider.engine
        self.Session = self.repository_provider.Session
        super().__init__(self.repository_provider)

    def close(self) -> None:
        self.engine.dispose()


def ensure_database_exists(database_url: str) -> None:
    """Create the target PostgreSQL database when it does not exist."""
    try:
        url = make_url(database_url)
    except Exception:
        return
    if url.get_backend_name() != "postgresql":
        return

    database_name = (url.database or "").strip()
    if not database_name:
        return

    errors: list[str] = []
    for maintenance_database in _maintenance_databases(database_name):
        maintenance_url = url.set(database=maintenance_database)
        try:
            _ensure_postgres_database(maintenance_url, database_name)
            return
        except OperationalError as exc:
            errors.append(str(exc))
            continue

    if errors:
        raise RuntimeError(
            "Unable to connect to a PostgreSQL maintenance database to create "
            f"database '{database_name}'. Last error: {errors[-1]}"
        )


def _maintenance_databases(database_name: str) -> tuple[str, ...]:
    candidates = ("postgres", "template1")
    return tuple(database for database in candidates if database != database_name) or candidates


def _ensure_postgres_database(maintenance_url: URL, database_name: str) -> None:
    engine = create_engine(
        maintenance_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        future=True,
    )
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).scalar() is not None
            if exists:
                return
            quoted_name = engine.dialect.identifier_preparer.quote(database_name)
            try:
                connection.execute(text(f"CREATE DATABASE {quoted_name}"))
            except ProgrammingError:
                # Another process may have created the database after our existence check.
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                    {"database_name": database_name},
                ).scalar() is not None
                if not exists:
                    raise
    finally:
        engine.dispose()


__all__ = [
    "AccountModel",
    "AuditLogModel",
    "AuthKeyModel",
    "Base",
    "ChannelModel",
    "DatabaseStorageBackend",
    "ensure_database_exists",
    "ImageRecordModel",
    "PromptLibraryItemModel",
    "QuotaReservationModel",
    "RedeemCodeModel",
    "SessionModel",
    "SystemLogModel",
    "SystemSettingModel",
    "UserModel",
]
