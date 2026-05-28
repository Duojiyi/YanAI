from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from services.repositories.base import RepositoryValidationError
from services.storage.database_storage import DatabaseStorageBackend


class RepositoryDatabaseStorageTest(unittest.TestCase):
    def test_database_storage_persists_all_datasets_and_index_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "storage.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")

            storage.save_accounts([{"access_token": "token-a", "status": "正常", "quota": 3, "user_id": "chatgpt-user-a"}])
            storage.save_auth_keys([{"id": "key-a", "key_hash": "hash-a", "role": "admin", "enabled": True}])
            storage.save_users([{"id": "user-a", "email": "user@example.com", "role": "user", "status": "active", "quota": 5, "quota_used": 1}])
            storage.save_sessions([{"id": "session-a", "token_hash": "token-hash-a", "user_id": "user-a", "expires_at": "2026-06-01T00:00:00+00:00"}])
            storage.save_redeem_codes([{"id": "code-a", "code": "YAI-CODEA", "status": "enabled", "used_count": 0, "max_uses": 1}])
            storage.save_channels([{"id": "channel-a", "enabled": True, "priority": 10, "weight": 2}])
            storage.save_prompt_library([{"id": "prompt-a", "title": "A", "prompt": "Prompt", "category": "quick", "quick_access": True}])
            storage.save_image_records([{"id": "image-a", "owner_user_id": "user-a", "created_at": "2026-05-28 12:00:00", "channel": "internal_pool"}])

            self.assertEqual(storage.load_accounts()[0]["access_token"], "token-a")
            self.assertEqual(storage.load_auth_keys()[0]["id"], "key-a")
            self.assertEqual(storage.load_users()[0]["email"], "user@example.com")
            self.assertEqual(storage.load_sessions()[0]["token_hash"], "token-hash-a")
            self.assertEqual(storage.load_redeem_codes()[0]["code"], "YAI-CODEA")
            self.assertEqual(storage.load_channels()[0]["id"], "channel-a")
            self.assertEqual(storage.load_prompt_library()[0]["id"], "prompt-a")
            self.assertEqual(storage.load_image_records()[0]["id"], "image-a")

            health = storage.health_check()
            self.assertEqual(health["status"], "healthy")
            self.assertEqual(health["accounts_count"], 1)
            self.assertEqual(health["users_count"], 1)
            self.assertEqual(health["image_records_count"], 1)

            with storage.engine.connect() as connection:
                account = connection.execute(
                    text("SELECT access_token_hash, status, quota FROM accounts")
                ).mappings().one()
                self.assertEqual(account["access_token_hash"], hashlib.sha256(b"token-a").hexdigest())
                self.assertEqual(account["status"], "正常")
                self.assertEqual(account["quota"], 3)
            storage.close()

    def test_duplicate_keys_are_reported_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "storage.db"
            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")

            with self.assertRaises(RepositoryValidationError):
                storage.save_accounts([
                    {"access_token": "token-a", "user_id": "u1"},
                    {"access_token": "token-a", "user_id": "u2"},
                ])
            storage.close()

    def test_legacy_database_tables_are_readable_and_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"
            url = f"sqlite:///{db_path.as_posix()}"
            engine = create_engine(url)
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, access_token VARCHAR(2048), data TEXT NOT NULL)"))
                connection.execute(
                    text("INSERT INTO accounts (access_token, data) VALUES (:token, :data)"),
                    {"token": "legacy-token", "data": json.dumps({"access_token": "legacy-token", "status": "正常"})},
                )
            engine.dispose()

            storage = DatabaseStorageBackend(url)
            self.assertEqual(storage.load_accounts(), [{"access_token": "legacy-token", "status": "正常"}])
            storage.save_accounts(storage.load_accounts())

            with storage.engine.connect() as connection:
                row = connection.execute(
                    text("SELECT access_token_hash, position FROM accounts")
                ).mappings().one()
                self.assertEqual(row["access_token_hash"], hashlib.sha256(b"legacy-token").hexdigest())
                self.assertEqual(row["position"], 0)
            storage.close()


if __name__ == "__main__":
    unittest.main()
