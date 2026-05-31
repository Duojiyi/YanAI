import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.prompts as prompts_api
from services.prompt_service import PromptLibraryService
from services.storage.json_storage import JSONStorageBackend


class PromptApiTests(unittest.TestCase):
    def test_upload_prompt_asset_route_is_not_shadowed_by_prompt_id_route(self) -> None:
        self._assert_upload_prompt_asset("/api/admin/prompts/assets")

    def test_upload_prompt_asset_has_stable_non_dynamic_route(self) -> None:
        self._assert_upload_prompt_asset("/api/admin/prompt-assets")

    def _assert_upload_prompt_asset(self, path: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            service = PromptLibraryService(
                JSONStorageBackend(root / "accounts.json"),
                bootstrap_paths=(),
                assets_dir=root / "assets",
            )
            original_service = prompts_api.prompt_library_service
            original_require_admin = prompts_api.require_admin
            try:
                prompts_api.prompt_library_service = service
                prompts_api.require_admin = lambda authorization: {"id": "admin", "role": "admin"}

                app = FastAPI()
                app.include_router(prompts_api.create_router())
                response = TestClient(app).post(
                    path,
                    files={"file": ("sample.png", b"image-bytes", "image/png")},
                )
            finally:
                prompts_api.prompt_library_service = original_service
                prompts_api.require_admin = original_require_admin

            self.assertEqual(response.status_code, 200, response.text)
            url = response.json()["url"]
            self.assertTrue(url.startswith("/prompt-assets/"))
            relative_path = Path(*url.removeprefix("/prompt-assets/").split("/"))
            self.assertTrue((root / "assets" / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()
