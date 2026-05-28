from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import migrate_storage
from services.storage.database_storage import DatabaseStorageBackend


class FullStorageMigrationTest(unittest.TestCase):
    def test_json_to_sqlite_migrates_every_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "target.db"
            self._write_json(root / "accounts.json", [{"access_token": "token-a", "status": "正常", "quota": 2}])
            self._write_json(root / "auth_keys.json", {"items": [{"id": "key-a", "key_hash": "hash-a", "role": "admin", "enabled": True}]})
            self._write_json(root / "users.json", [{"id": "user-a", "email": "a@example.com", "role": "user", "status": "active"}])
            self._write_json(root / "sessions.json", [{"id": "session-a", "token_hash": "hash-session", "user_id": "user-a"}])
            self._write_json(root / "redeem_codes.json", [{"id": "redeem-a", "code": "YAI-AAAA", "status": "enabled"}])
            self._write_json(root / "channels.json", [{"id": "channel-a", "enabled": True, "priority": 1, "weight": 1}])
            self._write_json(root / "prompt_library.json", [{"id": "prompt-a", "title": "A", "prompt": "Do it", "quick_access": True}])
            self._write_json(root / "image_records.json", [{"id": "image-a", "owner_user_id": "user-a", "channel": "internal_pool"}])

            with mock.patch.object(migrate_storage, "DATA_DIR", root), mock.patch.dict(
                os.environ,
                {"DATABASE_URL": f"sqlite:///{db_path.as_posix()}"},
                clear=False,
            ):
                migrate_storage.migrate_data("json", "sqlite")

            storage = DatabaseStorageBackend(f"sqlite:///{db_path.as_posix()}")
            self.assertEqual(len(storage.load_accounts()), 1)
            self.assertEqual(len(storage.load_auth_keys()), 1)
            self.assertEqual(len(storage.load_users()), 1)
            self.assertEqual(len(storage.load_sessions()), 1)
            self.assertEqual(len(storage.load_redeem_codes()), 1)
            self.assertEqual(len(storage.load_channels()), 1)
            self.assertEqual(len(storage.load_prompt_library()), 1)
            self.assertEqual(len(storage.load_image_records()), 1)
            storage.close()

    def test_full_export_payload_round_trip_parser(self) -> None:
        payload = {
            "version": 1,
            "datasets": {
                "accounts": [{"access_token": "token-a"}],
                "auth_keys": [{"id": "key-a"}],
            },
        }

        parsed = migrate_storage._parse_import_payload(payload)
        self.assertEqual(parsed["accounts"], [{"access_token": "token-a"}])
        self.assertEqual(parsed["auth_keys"], [{"id": "key-a"}])
        self.assertEqual(parsed["users"], [])

        legacy = migrate_storage._parse_import_payload([{"access_token": "token-only"}])
        self.assertEqual(legacy["accounts"], [{"access_token": "token-only"}])
        self.assertEqual(legacy["image_records"], [])

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
