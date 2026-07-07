from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import webdav_service


class WebDAVServiceTests(unittest.TestCase):
    def test_user_config_blank_password_preserves_existing_secret(self) -> None:
        users = [
            {
                "id": "user-a",
                "email": "user@example.com",
                "role": "user",
                "status": "active",
                "webdav_config": {
                    "enabled": True,
                    "url": "https://dav.example/old",
                    "username": "old-user",
                    "password": "old-secret",
                    "root_path": "old-root",
                },
            }
        ]

        class FakeStorage:
            def load_users(self) -> list[dict[str, object]]:
                return users

            def save_users(self, next_users: list[dict[str, object]]) -> None:
                users[:] = next_users

        fake_config = SimpleNamespace(
            get_repository_provider=lambda: None,
            get_storage_backend=lambda: FakeStorage(),
        )

        with mock.patch.object(webdav_service, "config", fake_config):
            saved = webdav_service.save_webdav_config(
                "user",
                {
                    "enabled": True,
                    "url": "https://dav.example/new",
                    "username": "new-user",
                    "password": "",
                    "root_path": "new-root",
                },
                user_id="user-a",
            )

        self.assertTrue(saved["password_set"])
        self.assertNotIn("password", saved)
        self.assertEqual(users[0]["webdav_config"]["password"], "old-secret")
        self.assertEqual(users[0]["webdav_config"]["url"], "https://dav.example/new")

    def test_sync_uploads_local_image_and_updates_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir) / "images"
            image_path = images_dir / "2026" / "06" / "05" / "sample.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image-bytes")
            records = [
                {
                    "id": "image-a",
                    "record_id": "image-a",
                    "url": "http://127.0.0.1:8000/images/2026/06/05/sample.png",
                    "created_at": "2026-06-05 12:00:00",
                },
                {
                    "id": "image-b",
                    "record_id": "image-b",
                    "url": "http://127.0.0.1:8000/images/2026/06/05/sample.png",
                    "created_at": "2026-06-05 12:01:00",
                }
            ]

            class FakeStorage:
                def load_image_records(self) -> list[dict[str, object]]:
                    return records

                def save_image_records(self, next_records: list[dict[str, object]]) -> None:
                    records[:] = next_records

            fake_config = SimpleNamespace(
                data={
                    webdav_service.ADMIN_CONFIG_KEY: {
                        "enabled": True,
                        "url": "https://dav.example/base",
                        "public_url": "https://cdn.example/public",
                        "username": "dav-user",
                        "password": "dav-pass",
                        "root_path": "YanAI",
                    }
                },
                images_dir=images_dir,
                _save=lambda: None,
                get_repository_provider=lambda: None,
                get_storage_backend=lambda: FakeStorage(),
            )
            calls: list[tuple[str, str, bytes | None, dict[str, str] | None]] = []

            def fake_request(
                method: str,
                url: str,
                *,
                data: bytes | None = None,
                headers: dict[str, str] | None = None,
                timeout: int = 30,
            ) -> int:
                calls.append((method, url, data, headers))
                return 201 if method in {"MKCOL", "PUT"} else 200

            with (
                mock.patch.object(webdav_service, "config", fake_config),
                mock.patch.object(webdav_service, "_request", side_effect=fake_request),
                mock.patch.object(webdav_service, "china_now_text", return_value="2026-06-05 20:00:00"),
            ):
                result = webdav_service.sync_images_to_webdav(
                    scope="admin",
                    identity={"id": "admin", "role": "admin"},
                    filters={"record_ids": ["image-a"]},
                )

        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["total"], 1)
        self.assertEqual(records[0]["webdav_status"], "synced")
        self.assertEqual(records[0]["webdav_synced_at"], "2026-06-05 20:00:00")
        self.assertNotIn("webdav_status", records[1])
        self.assertEqual(
            records[0]["webdav_url"],
            "https://cdn.example/public/YanAI/2026/06/05/sample.png",
        )
        self.assertEqual(result["items"][0]["url"], "https://cdn.example/public/YanAI/2026/06/05/sample.png")
        self.assertEqual(result["items"][0]["upload_url"], "https://dav.example/base/YanAI/2026/06/05/sample.png")
        self.assertIn(("PUT", "https://dav.example/base/YanAI/2026/06/05/sample.png"), [(method, url) for method, url, _, _ in calls])
        self.assertTrue(any(method == "MKCOL" and url.endswith("/YanAI/2026/06/05") for method, url, _, _ in calls))
        self.assertEqual(fake_config.data[webdav_service.ADMIN_CONFIG_KEY]["last_sync_at"], "2026-06-05 20:00:00")

    def test_upload_generated_image_bytes_puts_directly_to_webdav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir) / "images"
            images_dir.mkdir()
            fake_config = SimpleNamespace(
                data={
                    webdav_service.ADMIN_CONFIG_KEY: {
                        "enabled": True,
                        "url": "https://dav.example/base",
                        "public_url": "https://cdn.example/public",
                        "username": "dav-user",
                        "password": "dav-pass",
                        "root_path": "YanAI",
                    }
                },
                images_dir=images_dir,
                _save=lambda: None,
                get_repository_provider=lambda: None,
            )
            calls: list[tuple[str, str, bytes | None, dict[str, str] | None]] = []

            def fake_request(
                method: str,
                url: str,
                *,
                data: bytes | None = None,
                headers: dict[str, str] | None = None,
                timeout: int = 30,
            ) -> int:
                calls.append((method, url, data, headers))
                return 201 if method in {"MKCOL", "PUT"} else 200

            with (
                mock.patch.object(webdav_service, "config", fake_config),
                mock.patch.object(webdav_service, "_request", side_effect=fake_request),
                mock.patch.object(webdav_service, "china_now_text", return_value="2026-06-05 20:00:00"),
                mock.patch.object(webdav_service.uuid, "uuid4", return_value=SimpleNamespace(hex="unique")),
            ):
                result = webdav_service.upload_generated_image_bytes(
                    {"id": "admin", "role": "admin"},
                    b"image-bytes",
                )
            local_files = list(images_dir.rglob("*"))

        filename = f"{hashlib.md5(b'image-bytes').hexdigest()}_unique.png"
        self.assertIsNotNone(result)
        self.assertEqual(result["url"], f"https://cdn.example/public/YanAI/2026/06/05/{filename}")
        self.assertEqual(result["upload_url"], f"https://dav.example/base/YanAI/2026/06/05/{filename}")
        put_calls = [call for call in calls if call[0] == "PUT"]
        self.assertEqual(len(put_calls), 1)
        self.assertEqual(put_calls[0][2], b"image-bytes")
        self.assertEqual((put_calls[0][3] or {}).get("Content-Type"), "image/png")
        self.assertEqual(local_files, [])
        self.assertEqual(fake_config.data[webdav_service.ADMIN_CONFIG_KEY]["last_sync_result"]["uploaded"], 1)

    def test_upload_generated_image_bytes_uses_admin_config_for_user_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir) / "images"
            images_dir.mkdir()
            fake_config = SimpleNamespace(
                data={
                    webdav_service.ADMIN_CONFIG_KEY: {
                        "enabled": True,
                        "url": "https://dav.example/base",
                        "public_url": "https://cdn.example/public",
                        "username": "dav-user",
                        "password": "dav-pass",
                        "root_path": "AdminRoot",
                    }
                },
                images_dir=images_dir,
                _save=lambda: None,
                get_repository_provider=lambda: None,
            )
            calls: list[tuple[str, str, bytes | None, dict[str, str] | None]] = []

            def fake_request(
                method: str,
                url: str,
                *,
                data: bytes | None = None,
                headers: dict[str, str] | None = None,
                timeout: int = 30,
            ) -> int:
                calls.append((method, url, data, headers))
                return 201 if method in {"MKCOL", "PUT"} else 200

            with (
                mock.patch.object(webdav_service, "config", fake_config),
                mock.patch.object(webdav_service, "_request", side_effect=fake_request),
                mock.patch.object(webdav_service, "china_now_text", return_value="2026-06-05 20:00:00"),
                mock.patch.object(webdav_service.uuid, "uuid4", return_value=SimpleNamespace(hex="unique")),
            ):
                result = webdav_service.upload_generated_image_bytes(
                    {"id": "user-a", "role": "user"},
                    b"image-bytes",
                )

        filename = f"{hashlib.md5(b'image-bytes').hexdigest()}_unique.png"
        self.assertIsNotNone(result)
        self.assertEqual(result["scope"], "admin")
        self.assertEqual(result["url"], f"https://cdn.example/public/AdminRoot/2026/06/05/{filename}")
        self.assertEqual(result["upload_url"], f"https://dav.example/base/AdminRoot/2026/06/05/{filename}")
        self.assertIn(("PUT", f"https://dav.example/base/AdminRoot/2026/06/05/{filename}"), [(method, url) for method, url, _, _ in calls])

    def test_sync_created_records_uses_admin_config_for_user_identity(self) -> None:
        identity = {"id": "user-a", "role": "user"}
        with (
            mock.patch.object(
                webdav_service,
                "get_webdav_config",
                return_value={"enabled": True, "url": "https://dav.example/base"},
            ) as get_config,
            mock.patch.object(webdav_service, "sync_images_to_webdav", return_value={"scope": "admin"}) as sync_images,
        ):
            result = webdav_service.sync_created_records_to_webdav(identity, [{"record_id": "image-a"}])

        self.assertEqual(result, {"scope": "admin"})
        get_config.assert_called_once_with("admin", user_id="", include_password=True)
        sync_images.assert_called_once_with(
            scope="admin",
            identity=identity,
            filters={"record_ids": ["image-a"]},
        )


if __name__ == "__main__":
    unittest.main()
