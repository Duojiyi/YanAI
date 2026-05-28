from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from services.repositories.base import (
    AccountRepository,
    AuthKeyRepository,
    ChannelRepository,
    DatasetRepository,
    ImageRecordRepository,
    PromptRepository,
    RedeemCodeRepository,
    RepositoryProvider,
    RepositoryValidationError,
    SessionRepository,
    SystemConfigRepository,
    UserRepository,
)


Base = declarative_base()
SCHEMA_VERSION = "001_repository_schema"


def _json_column_type():
    return JSON().with_variant(JSONB(none_as_null=True), "postgresql")


class AccountRow(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    access_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(64), index=True)
    quota = Column(Integer)
    leased_until = Column(String(80), index=True)
    lease_owner = Column(String(255), index=True)
    updated_at = Column(String(80), index=True)
    data = Column(_json_column_type(), nullable=False)


class AuthKeyRow(Base):
    __tablename__ = "auth_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    key_id = Column(String(255), nullable=False, unique=True, index=True)
    key_hash = Column(String(255), index=True)
    role = Column(String(32), index=True)
    enabled = Column(Boolean, index=True)
    data = Column(_json_column_type(), nullable=False)


class UserRow(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    user_id = Column(String(255), nullable=False, unique=True, index=True)
    email = Column(String(320), index=True)
    role = Column(String(32), index=True)
    status = Column(String(32), index=True)
    quota = Column(Integer)
    quota_used = Column(Integer)
    data = Column(_json_column_type(), nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    session_id = Column(String(255), nullable=False, unique=True, index=True)
    token_hash = Column(String(255), index=True)
    user_id = Column(String(255), index=True)
    expires_at = Column(String(80), index=True)
    data = Column(_json_column_type(), nullable=False)


class RedeemCodeRow(Base):
    __tablename__ = "redeem_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    redeem_id = Column(String(255), nullable=False, unique=True, index=True)
    code = Column(String(255), index=True)
    status = Column(String(32), index=True)
    used_count = Column(Integer)
    max_uses = Column(Integer)
    data = Column(_json_column_type(), nullable=False)


class ChannelRow(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    channel_id = Column(String(255), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, index=True)
    priority = Column(Integer, index=True)
    weight = Column(Integer)
    data = Column(_json_column_type(), nullable=False)


class PromptLibraryRow(Base):
    __tablename__ = "prompt_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    prompt_id = Column(String(255), nullable=False, unique=True, index=True)
    category = Column(String(255), index=True)
    quick_access = Column(Boolean, index=True)
    data = Column(_json_column_type(), nullable=False)


class ImageRecordRow(Base):
    __tablename__ = "image_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position = Column(Integer, nullable=False, default=0, index=True)
    record_id = Column(String(255), nullable=False, unique=True, index=True)
    owner_user_id = Column(String(255), index=True)
    created_at = Column(String(80), index=True)
    channel = Column(String(255), index=True)
    data = Column(_json_column_type(), nullable=False)


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"

    version = Column(String(255), primary_key=True)
    applied_at = Column(String(80), nullable=False)


@dataclass(frozen=True)
class RepositoryDefinition:
    dataset_name: str
    model: type[Base]
    primary_key: str
    key_column: str
    column_extractors: dict[str, Callable[[dict[str, Any]], Any]]
    unique_keys: tuple[str, ...] = ()
    key_transform: Callable[[str], str] | None = None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled", "active"}
    return bool(value)


def _data_copy(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


DEFINITIONS: dict[str, RepositoryDefinition] = {
    "accounts": RepositoryDefinition(
        dataset_name="accounts",
        model=AccountRow,
        primary_key="access_token",
        key_column="access_token_hash",
        key_transform=_hash,
        unique_keys=("user_id",),
        column_extractors={
            "access_token_hash": lambda item: _hash(_clean(item.get("access_token"))),
            "status": lambda item: _clean(item.get("status")) or None,
            "quota": lambda item: _int(item.get("quota")),
            "leased_until": lambda item: _clean(item.get("leased_until")) or None,
            "lease_owner": lambda item: _clean(item.get("lease_owner")) or None,
            "updated_at": lambda item: _clean(item.get("updated_at") or item.get("last_used_at")) or None,
        },
    ),
    "auth_keys": RepositoryDefinition(
        dataset_name="auth_keys",
        model=AuthKeyRow,
        primary_key="id",
        key_column="key_id",
        column_extractors={
            "key_id": lambda item: _clean(item.get("id")),
            "key_hash": lambda item: _clean(item.get("key_hash")) or None,
            "role": lambda item: _clean(item.get("role")) or None,
            "enabled": lambda item: _bool(item.get("enabled")),
        },
    ),
    "users": RepositoryDefinition(
        dataset_name="users",
        model=UserRow,
        primary_key="id",
        key_column="user_id",
        unique_keys=("email",),
        column_extractors={
            "user_id": lambda item: _clean(item.get("id")),
            "email": lambda item: _clean(item.get("email")).lower() or None,
            "role": lambda item: _clean(item.get("role")) or None,
            "status": lambda item: _clean(item.get("status")) or None,
            "quota": lambda item: _int(item.get("quota")),
            "quota_used": lambda item: _int(item.get("quota_used")),
        },
    ),
    "sessions": RepositoryDefinition(
        dataset_name="sessions",
        model=SessionRow,
        primary_key="id",
        key_column="session_id",
        unique_keys=("token_hash",),
        column_extractors={
            "session_id": lambda item: _clean(item.get("id")),
            "token_hash": lambda item: _clean(item.get("token_hash")) or None,
            "user_id": lambda item: _clean(item.get("user_id")) or None,
            "expires_at": lambda item: _clean(item.get("expires_at")) or None,
        },
    ),
    "redeem_codes": RepositoryDefinition(
        dataset_name="redeem_codes",
        model=RedeemCodeRow,
        primary_key="id",
        key_column="redeem_id",
        unique_keys=("code",),
        column_extractors={
            "redeem_id": lambda item: _clean(item.get("id")),
            "code": lambda item: _clean(item.get("code")).upper() or None,
            "status": lambda item: _clean(item.get("status")) or None,
            "used_count": lambda item: _int(item.get("used_count")),
            "max_uses": lambda item: _int(item.get("max_uses")),
        },
    ),
    "channels": RepositoryDefinition(
        dataset_name="channels",
        model=ChannelRow,
        primary_key="id",
        key_column="channel_id",
        column_extractors={
            "channel_id": lambda item: _clean(item.get("id")),
            "enabled": lambda item: _bool(item.get("enabled")),
            "priority": lambda item: _int(item.get("priority")),
            "weight": lambda item: _int(item.get("weight")),
        },
    ),
    "prompt_library": RepositoryDefinition(
        dataset_name="prompt_library",
        model=PromptLibraryRow,
        primary_key="id",
        key_column="prompt_id",
        column_extractors={
            "prompt_id": lambda item: _clean(item.get("id")),
            "category": lambda item: _clean(item.get("category")) or None,
            "quick_access": lambda item: _bool(item.get("quick_access")),
        },
    ),
    "image_records": RepositoryDefinition(
        dataset_name="image_records",
        model=ImageRecordRow,
        primary_key="id",
        key_column="record_id",
        column_extractors={
            "record_id": lambda item: _clean(item.get("id")),
            "owner_user_id": lambda item: _clean(item.get("owner_user_id")) or None,
            "created_at": lambda item: _clean(item.get("created_at")) or None,
            "channel": lambda item: _clean(item.get("channel")) or None,
        },
    ),
}


class SQLAlchemyDatasetRepository(DatasetRepository):
    def __init__(self, session_factory: sessionmaker[Session], definition: RepositoryDefinition):
        self._session_factory = session_factory
        self._definition = definition
        self.dataset_name = definition.dataset_name
        self.primary_key = definition.primary_key
        self.unique_keys = definition.unique_keys

    @property
    def model(self) -> type[Base]:
        return self._definition.model

    @property
    def key_column(self):
        return getattr(self.model, self._definition.key_column)

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                select(self.model).order_by(self.model.position.asc(), self.model.id.asc())
            ).scalars()
            return [_data_copy(row.data) for row in rows if _data_copy(row.data)]

    def replace_all(self, items: list[dict[str, Any]]) -> None:
        normalized = self._validate_items(items)
        db_keys = [self._database_key(item) for item in normalized]
        with self._session_factory() as session:
            with session.begin():
                for position, item in enumerate(normalized):
                    self._upsert_in_session(session, item, position=position)
                if db_keys:
                    session.execute(
                        delete(self.model).where(
                            or_(self.key_column.is_(None), self.key_column.not_in(db_keys))
                        )
                    )
                else:
                    session.execute(delete(self.model))

    def upsert(self, item: dict[str, Any]) -> None:
        normalized = self._validate_items([item])[0]
        with self._session_factory() as session:
            with session.begin():
                self._upsert_in_session(session, normalized)

    def delete(self, key: str) -> bool:
        db_key = self._database_key_from_text(key)
        with self._session_factory() as session:
            with session.begin():
                result = session.execute(delete(self.model).where(self.key_column == db_key))
            return bool(result.rowcount)

    def count(self) -> int:
        with self._session_factory() as session:
            return int(session.execute(select(func.count()).select_from(self.model)).scalar_one())

    def key_set(self) -> set[str]:
        return {
            key
            for item in self.list()
            if (key := _clean(item.get(self.primary_key)))
        }

    def _upsert_in_session(self, session: Session, item: dict[str, Any], *, position: int | None = None) -> None:
        db_key = self._database_key(item)
        row = session.execute(select(self.model).where(self.key_column == db_key)).scalar_one_or_none()
        if row is None:
            row = self.model()
            session.add(row)
        if position is not None:
            row.position = position
        elif row.position is None:
            row.position = 0
        for column_name, extractor in self._definition.column_extractors.items():
            setattr(row, column_name, extractor(item))
        row.data = dict(item)

    def _database_key(self, item: dict[str, Any]) -> str:
        return self._database_key_from_text(_clean(item.get(self.primary_key)))

    def _database_key_from_text(self, value: str) -> str:
        value = _clean(value)
        if not value:
            return ""
        transform = self._definition.key_transform
        return transform(value) if transform else value

    def _validate_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            raise RepositoryValidationError(f"{self.dataset_name}: expected list of objects")
        normalized: list[dict[str, Any]] = []
        problems: list[str] = []
        primary_seen: dict[str, int] = {}
        unique_seen: dict[str, dict[str, int]] = {key: {} for key in self.unique_keys}

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                problems.append(f"index {index}: item is not an object")
                continue
            key = _clean(item.get(self.primary_key))
            if not key:
                problems.append(f"index {index}: missing primary key {self.primary_key!r}")
                continue
            if key in primary_seen:
                problems.append(
                    f"index {index}: duplicate primary key {self.primary_key!r} "
                    f"(first index {primary_seen[key]}, value_sha256={_hash(key)[:16]})"
                )
                continue
            primary_seen[key] = index
            for unique_key in self.unique_keys:
                value = _clean(item.get(unique_key))
                if not value:
                    continue
                seen_for_key = unique_seen[unique_key]
                if value in seen_for_key:
                    problems.append(
                        f"index {index}: duplicate unique key {unique_key!r} "
                        f"(first index {seen_for_key[value]}, value_sha256={_hash(value)[:16]})"
                    )
                    continue
                seen_for_key[value] = index
            normalized.append(dict(item))

        if problems:
            preview = "; ".join(problems[:10])
            if len(problems) > 10:
                preview += f"; ... {len(problems) - 10} more"
            raise RepositoryValidationError(f"{self.dataset_name}: validation failed: {preview}")
        return normalized


class SQLAlchemyAccountRepository(SQLAlchemyDatasetRepository, AccountRepository):
    pass


class SQLAlchemyAuthKeyRepository(SQLAlchemyDatasetRepository, AuthKeyRepository):
    pass


class SQLAlchemyUserRepository(SQLAlchemyDatasetRepository, UserRepository):
    pass


class SQLAlchemySessionRepository(SQLAlchemyDatasetRepository, SessionRepository):
    pass


class SQLAlchemyRedeemCodeRepository(SQLAlchemyDatasetRepository, RedeemCodeRepository):
    pass


class SQLAlchemyChannelRepository(SQLAlchemyDatasetRepository, ChannelRepository):
    pass


class SQLAlchemyPromptRepository(SQLAlchemyDatasetRepository, PromptRepository):
    pass


class SQLAlchemyImageRecordRepository(SQLAlchemyDatasetRepository, ImageRecordRepository):
    pass


class MemorySystemConfigRepository(SystemConfigRepository):
    def __init__(self):
        self._settings: dict[str, Any] = {}

    def list_settings(self) -> dict[str, Any]:
        return dict(self._settings)

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[str(key)] = value

    def delete_setting(self, key: str) -> bool:
        return self._settings.pop(str(key), None) is not None


class SQLAlchemyRepositoryProvider(RepositoryProvider):
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self._ensure_legacy_tables_have_columns()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self._accounts = SQLAlchemyAccountRepository(self.Session, DEFINITIONS["accounts"])
        self._auth_keys = SQLAlchemyAuthKeyRepository(self.Session, DEFINITIONS["auth_keys"])
        self._users = SQLAlchemyUserRepository(self.Session, DEFINITIONS["users"])
        self._sessions = SQLAlchemySessionRepository(self.Session, DEFINITIONS["sessions"])
        self._redeem_codes = SQLAlchemyRedeemCodeRepository(self.Session, DEFINITIONS["redeem_codes"])
        self._channels = SQLAlchemyChannelRepository(self.Session, DEFINITIONS["channels"])
        self._prompts = SQLAlchemyPromptRepository(self.Session, DEFINITIONS["prompt_library"])
        self._image_records = SQLAlchemyImageRecordRepository(self.Session, DEFINITIONS["image_records"])
        self._system_config = MemorySystemConfigRepository()
        self._stamp_schema_version()

    @property
    def accounts(self) -> AccountRepository:
        return self._accounts

    @property
    def auth_keys(self) -> AuthKeyRepository:
        return self._auth_keys

    @property
    def users(self) -> UserRepository:
        return self._users

    @property
    def sessions(self) -> SessionRepository:
        return self._sessions

    @property
    def redeem_codes(self) -> RedeemCodeRepository:
        return self._redeem_codes

    @property
    def channels(self) -> ChannelRepository:
        return self._channels

    @property
    def prompts(self) -> PromptRepository:
        return self._prompts

    @property
    def image_records(self) -> ImageRecordRepository:
        return self._image_records

    @property
    def system_config(self) -> SystemConfigRepository:
        return self._system_config

    def repositories(self) -> tuple[DatasetRepository, ...]:
        return (
            self.accounts,
            self.auth_keys,
            self.users,
            self.sessions,
            self.redeem_codes,
            self.channels,
            self.prompts,
            self.image_records,
        )

    def health_check(self) -> dict[str, Any]:
        try:
            with self.Session() as session:
                session.execute(text("SELECT 1"))
            counts = {f"{repo.dataset_name}_count": repo.count() for repo in self.repositories()}
            return {
                "status": "healthy",
                "backend": "database",
                "db_type": self._db_type(),
                "database_url": self._mask_password(self.database_url),
                "schema_version": SCHEMA_VERSION,
                **counts,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "backend": "database",
                "db_type": self._db_type(),
                "error": str(exc),
            }

    def get_backend_info(self) -> dict[str, Any]:
        return {
            "type": "database",
            "db_type": self._db_type(),
            "description": f"数据库存储 ({self._db_type()})",
            "database_url": self._mask_password(self.database_url),
            "repository": "sqlalchemy",
            "schema_version": SCHEMA_VERSION,
        }

    def _stamp_schema_version(self) -> None:
        with self.Session() as session:
            with session.begin():
                current = session.get(SchemaMigrationRow, SCHEMA_VERSION)
                if current is None:
                    session.add(
                        SchemaMigrationRow(
                            version=SCHEMA_VERSION,
                            applied_at=datetime.now(timezone.utc).isoformat(),
                        )
                    )

    def _ensure_legacy_tables_have_columns(self) -> None:
        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())
        column_specs = _column_specs()
        preparer = self.engine.dialect.identifier_preparer
        with self.engine.begin() as connection:
            for table_name, specs in column_specs.items():
                if table_name not in existing_tables:
                    continue
                existing_columns = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }
                for column_name, sql_type in specs.items():
                    if column_name in existing_columns:
                        continue
                    connection.execute(
                        text(
                            f"ALTER TABLE {preparer.quote(table_name)} "
                            f"ADD COLUMN {preparer.quote(column_name)} {sql_type}"
                        )
                    )

    def _db_type(self) -> str:
        url = self.database_url.lower()
        if "sqlite" in url:
            return "sqlite"
        if "postgresql" in url or "postgres" in url:
            return "postgresql"
        if "mysql" in url:
            return "mysql"
        return "unknown"

    @staticmethod
    def _mask_password(url: str) -> str:
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


def _column_specs() -> dict[str, dict[str, str]]:
    return {
        "accounts": {
            "position": "INTEGER",
            "access_token_hash": "VARCHAR(64)",
            "status": "VARCHAR(64)",
            "quota": "INTEGER",
            "leased_until": "VARCHAR(80)",
            "lease_owner": "VARCHAR(255)",
            "updated_at": "VARCHAR(80)",
        },
        "auth_keys": {
            "position": "INTEGER",
            "key_id": "VARCHAR(255)",
            "key_hash": "VARCHAR(255)",
            "role": "VARCHAR(32)",
            "enabled": "BOOLEAN",
        },
        "users": {
            "position": "INTEGER",
            "user_id": "VARCHAR(255)",
            "email": "VARCHAR(320)",
            "role": "VARCHAR(32)",
            "status": "VARCHAR(32)",
            "quota": "INTEGER",
            "quota_used": "INTEGER",
        },
        "sessions": {
            "position": "INTEGER",
            "session_id": "VARCHAR(255)",
            "token_hash": "VARCHAR(255)",
            "user_id": "VARCHAR(255)",
            "expires_at": "VARCHAR(80)",
        },
        "redeem_codes": {
            "position": "INTEGER",
            "redeem_id": "VARCHAR(255)",
            "code": "VARCHAR(255)",
            "status": "VARCHAR(32)",
            "used_count": "INTEGER",
            "max_uses": "INTEGER",
        },
        "channels": {
            "position": "INTEGER",
            "channel_id": "VARCHAR(255)",
            "enabled": "BOOLEAN",
            "priority": "INTEGER",
            "weight": "INTEGER",
        },
        "prompt_library": {
            "position": "INTEGER",
            "prompt_id": "VARCHAR(255)",
            "category": "VARCHAR(255)",
            "quick_access": "BOOLEAN",
        },
        "image_records": {
            "position": "INTEGER",
            "record_id": "VARCHAR(255)",
            "owner_user_id": "VARCHAR(255)",
            "created_at": "VARCHAR(80)",
            "channel": "VARCHAR(255)",
        },
    }
