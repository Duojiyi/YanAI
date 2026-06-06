from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError

from services.storage.database_storage import ensure_database_exists
from services.storage.factory import _mask_password, _normalize_database_url, create_storage_backend


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakeConnection:
    def __init__(self, existing_database: bool):
        self.existing_database = existing_database
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "pg_database" in sql:
            return _ScalarResult(1 if self.existing_database else None)
        return _ScalarResult(None)


class _FakeEngine:
    def __init__(self, connection: _FakeConnection):
        from sqlalchemy.dialects import postgresql

        self.connection = connection
        self.dialect = postgresql.dialect()
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


class StorageFactoryTest(unittest.TestCase):
    def test_normalize_database_url_encodes_raw_password_characters(self) -> None:
        url = _normalize_database_url("postgresql://yanai:pa@ss@@192.3.60.166:5432/yanai")

        parsed = make_url(url)
        self.assertEqual(parsed.username, "yanai")
        self.assertEqual(parsed.password, "pa@ss@")
        self.assertEqual(parsed.host, "192.3.60.166")
        self.assertEqual(parsed.database, "yanai")
        self.assertEqual(_mask_password(url), "postgresql://yanai:****@192.3.60.166:5432/yanai")

    def test_normalize_database_url_strips_wrapping_quotes(self) -> None:
        url = _normalize_database_url("'postgresql://yanai:pass@192.3.60.166:5432/yanai'")

        parsed = make_url(url)
        self.assertEqual(parsed.username, "yanai")
        self.assertEqual(parsed.password, "pass")
        self.assertEqual(parsed.host, "192.3.60.166")

    def test_normalize_database_url_keeps_encoded_password_idempotent(self) -> None:
        url = "postgresql://yanai:pa%40ss%40@192.3.60.166:5432/yanai"

        self.assertEqual(_normalize_database_url(url), url)

    def test_normalize_database_url_keeps_at_signs_in_path_and_query(self) -> None:
        url = "postgresql://yanai:pass@192.3.60.166:5432/yanai?application_name=a@b"

        self.assertEqual(_normalize_database_url(url), url)

    def test_normalize_database_url_ignores_sqlite_file_paths(self) -> None:
        url = "sqlite:///tmp/db@local.sqlite3"

        self.assertEqual(_normalize_database_url(url), url)

    def test_create_database_storage_backend_strips_wrapping_quotes_from_env(self) -> None:
        env = {
            "STORAGE_BACKEND": '"postgres"',
            "DATABASE_URL": '"postgresql://yanai:pass@127.0.0.1:5432/yanai_dev"',
        }

        with mock.patch.dict("os.environ", env, clear=True), mock.patch(
            "services.storage.factory.DatabaseStorageBackend"
        ) as backend_cls:
            create_storage_backend(Path("data"))

        backend_cls.assert_called_once_with("postgresql://yanai:pass@127.0.0.1:5432/yanai_dev")

    def test_create_database_storage_backend_reads_config_json_when_env_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "STORAGE_BACKEND": "postgres",
                        "DATABASE_URL": "postgresql://yanai:pass@127.0.0.1:5432/yanai_from_config",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
                "services.storage.factory.DatabaseStorageBackend"
            ) as backend_cls:
                create_storage_backend(data_dir)

        backend_cls.assert_called_once_with("postgresql://yanai:pass@127.0.0.1:5432/yanai_from_config")

    def test_env_storage_backend_overrides_config_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "STORAGE_BACKEND": "postgres",
                        "DATABASE_URL": "postgresql://yanai:pass@127.0.0.1:5432/yanai_from_config",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {"STORAGE_BACKEND": "json"}, clear=True), mock.patch(
                "services.storage.factory.JSONStorageBackend"
            ) as backend_cls:
                create_storage_backend(data_dir)

        backend_cls.assert_called_once_with(data_dir / "accounts.json", data_dir / "auth_keys.json")

    def test_postgres_database_is_created_when_missing(self) -> None:
        connection = _FakeConnection(existing_database=False)
        engine = _FakeEngine(connection)

        with mock.patch("services.storage.database_storage.create_engine", return_value=engine) as create_engine_mock:
            ensure_database_exists("postgresql://yanai:pass@127.0.0.1:5432/yanai_dev")

        maintenance_url = create_engine_mock.call_args.args[0]
        self.assertEqual(maintenance_url.database, "postgres")
        self.assertIn("SELECT 1 FROM pg_database", connection.statements[0])
        self.assertIn("CREATE DATABASE yanai_dev", connection.statements[1])
        self.assertTrue(engine.disposed)

    def test_postgres_database_creation_falls_back_to_template1(self) -> None:
        connection = _FakeConnection(existing_database=True)
        fallback_engine = _FakeEngine(connection)

        def create_engine_side_effect(url, **kwargs):
            if url.database == "postgres":
                raise OperationalError("connect", None, Exception("missing maintenance db"))
            return fallback_engine

        with mock.patch("services.storage.database_storage.create_engine", side_effect=create_engine_side_effect) as create_engine_mock:
            ensure_database_exists("postgresql://yanai:pass@127.0.0.1:5432/yanai_dev")

        self.assertEqual(create_engine_mock.call_args.args[0].database, "template1")
        self.assertEqual(len(connection.statements), 1)

    def test_postgres_database_creation_skips_non_postgres_urls(self) -> None:
        with mock.patch("services.storage.database_storage.create_engine") as create_engine_mock:
            ensure_database_exists("sqlite:///data/accounts.db")

        create_engine_mock.assert_not_called()

    def test_create_git_storage_backend_uses_dataset_path_env_vars(self) -> None:
        env = {
            "STORAGE_BACKEND": "git",
            "GIT_REPO_URL": "https://github.com/example/private-data.git",
            "GIT_TOKEN": "token",
            "GIT_BRANCH": "main",
            "GIT_FILE_PATH": "data/accounts.json",
            "GIT_AUTH_KEYS_FILE_PATH": "data/auth_keys.json",
            "GIT_USERS_FILE_PATH": "data/users.json",
            "GIT_SESSIONS_FILE_PATH": "data/sessions.json",
            "GIT_REDEEM_CODES_FILE_PATH": "data/redeem_codes.json",
            "GIT_CHANNELS_FILE_PATH": "data/channels.json",
            "GIT_PROMPT_LIBRARY_FILE_PATH": "data/prompt_library.json",
            "GIT_IMAGE_RECORDS_FILE_PATH": "data/image_records.json",
        }

        with mock.patch.dict("os.environ", env, clear=True), mock.patch(
            "services.storage.factory.GitStorageBackend"
        ) as backend_cls:
            create_storage_backend(Path("data"))

        backend_cls.assert_called_once_with(
            repo_url="https://github.com/example/private-data.git",
            token="token",
            branch="main",
            file_path="data/accounts.json",
            auth_keys_file_path="data/auth_keys.json",
            users_file_path="data/users.json",
            sessions_file_path="data/sessions.json",
            redeem_codes_file_path="data/redeem_codes.json",
            channels_file_path="data/channels.json",
            prompt_library_file_path="data/prompt_library.json",
            image_records_file_path="data/image_records.json",
            local_cache_dir=Path("data") / "git_cache",
        )


if __name__ == "__main__":
    unittest.main()
