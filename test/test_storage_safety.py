from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.storage_safety import (
    DATASET_SPECS,
    audit_data_dir,
    create_backup,
    restore_backup,
    verify_backup,
)


class StorageSafetyTest(unittest.TestCase):
    def test_audit_reports_inventory_counts_and_primary_key_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root / "accounts.json",
                [
                    {"access_token": "token-a", "user_id": "user-a"},
                    {"access_token": "token-a", "user_id": "user-b"},
                    {"email": "missing-token@example.com"},
                ],
            )
            self._write_json(root / "auth_keys.json", {"items": [{"id": "key-a"}]})
            (root / "users.json").write_text("{bad json", encoding="utf-8")

            report = audit_data_dir(root)
            datasets = {item["name"]: item for item in report["datasets"]}

            self.assertEqual(set(datasets), {spec.name for spec in DATASET_SPECS})
            self.assertEqual(datasets["accounts"]["count"], 3)
            self.assertEqual(datasets["accounts"]["missing_primary_key_count"], 1)
            self.assertEqual(datasets["accounts"]["duplicate_primary_key_group_count"], 1)
            self.assertEqual(datasets["auth_keys"]["count"], 1)
            self.assertIn("line 1", datasets["users"]["json_error"])
            self.assertEqual(report["summary"]["invalid_json_files"], 1)
            self.assertEqual(report["summary"]["files_missing"], len(DATASET_SPECS) - 3)

    def test_backup_verify_and_restore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            backup_dir = root / "backup"
            restore_dir = root / "restore"
            self._write_json(root / "accounts.json", [{"access_token": "token-a"}])
            self._write_json(root / "users.json", [{"id": "user-a"}])
            self._write_json(root / "auth_keys.json", {"items": [{"id": "key-a"}]})

            manifest = create_backup(root, backup_dir)
            self.assertEqual(manifest["backup_dir"], str(backup_dir))
            self.assertTrue((backup_dir / "manifest.json").exists())

            verification = verify_backup(backup_dir)
            self.assertEqual(verification["status"], "ok")
            self.assertEqual(verification["problems"], [])

            result = restore_backup(backup_dir, restore_dir)
            self.assertEqual(
                set(result["copied_files"]),
                {"accounts.json", "auth_keys.json", "users.json"},
            )
            self.assertEqual(
                json.loads((restore_dir / "accounts.json").read_text(encoding="utf-8")),
                [{"access_token": "token-a"}],
            )

    def test_backup_verification_detects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            backup_dir = root / "backup"
            self._write_json(root / "accounts.json", [{"access_token": "token-a"}])

            create_backup(root, backup_dir)
            self._write_json(backup_dir / "accounts.json", [{"access_token": "changed"}])

            verification = verify_backup(backup_dir)
            self.assertEqual(verification["status"], "failed")
            self.assertTrue(any("checksum mismatch" in item for item in verification["problems"]))

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
