from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("STORAGE_BACKEND", "json")

import api.ai as api_ai
import api.support as api_support


class FakeAuthService:
    def __init__(self) -> None:
        self.identity = {
            "id": "user-a",
            "name": "Alice",
            "role": "user",
            "email": "alice@example.com",
        }
        self.reserved: list[tuple[str, int, str]] = []
        self.released: list[str] = []
        self.reserve_error: ValueError | None = None

    def authenticate(self, token: str):
        return self.identity if token == "user-token" else None

    def reserve_quota(self, user_id: str, amount: int, request_id: str):
        self.reserved.append((user_id, amount, request_id))
        if self.reserve_error is not None:
            raise self.reserve_error
        return {"user_id": user_id, "amount": amount, "request_id": request_id}

    def release_quota(self, request_id: str):
        self.released.append(request_id)
        return {"request_id": request_id}

    def confirm_quota(self, request_id: str, amount: int | None = None):
        return {"request_id": request_id, "amount": amount}

    def get_user_image_channel_config(self, user_id: str, *, include_api_key: bool = False):
        channel = {
            "enabled": True,
            "name": "Mine",
            "base_url": "https://personal.example",
            "models": ["gpt-image-2"],
            "timeout": 30,
        }
        if include_api_key:
            channel["api_key"] = "sk-personal"
        return channel


class FakeChannelService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.edit_calls: list[dict[str, object]] = []
        self.internal_pool_checked = False
        self.generation_result: tuple[dict[str, object], str] | None = None
        self.edit_result: tuple[dict[str, object], str] | None = None

    def has_usable_personal_channel(
        self,
        model: str | None,
        personal_channel: object = None,
        *,
        owner_user_id: str = "",
    ) -> bool:
        return True

    def call_generation(self, payload: dict[str, object]):
        self.calls.append(dict(payload))
        if self.generation_result is not None:
            return self.generation_result
        error = "个人渠道/Mine: 连接被上游重置（curl 35）。请检查个人渠道 Base URL 是否正确、API Key 是否有效、该渠道是否允许当前网络访问；如果系统设置里配置了代理，也请确认代理可用。"
        payload["_personal_channel_error"] = error
        payload["_channel_error"] = error
        return None

    def call_edit(self, payload: dict[str, object]):
        self.edit_calls.append(dict(payload))
        if self.edit_result is not None:
            return self.edit_result
        error = "个人渠道/Mine: 连接被上游重置（curl 35）。请检查个人渠道 Base URL 是否正确、API Key 是否有效、该渠道是否允许当前网络访问；如果系统设置里配置了代理，也请确认代理可用。"
        payload["_personal_channel_error"] = error
        payload["_channel_error"] = error
        return None

    def is_internal_pool_enabled(self) -> bool:
        self.internal_pool_checked = True
        return True


class PersonalImageChannelApiTests(unittest.TestCase):
    def test_admin_stream_generation_uses_external_channel(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        auth.identity = {
            "id": "admin",
            "name": "Admin",
            "role": "admin",
        }
        channels = FakeChannelService()
        channels.generation_result = (
            {"created": 1, "data": [{"url": "https://external.example/image.png"}]},
            "External",
        )
        record_calls: list[dict[str, object]] = []

        def fake_record_image_result(identity: dict[str, object], result: dict[str, object], **kwargs: object):
            record_calls.append(dict(kwargs))
            return []

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai, "record_image_result", fake_record_image_result),
        ):
            response = TestClient(app).post(
                "/v1/images/generations",
                headers={"Authorization": "Bearer user-token"},
                json={
                    "model": "gpt-image-2",
                    "prompt": "draw",
                    "n": 1,
                    "response_format": "url",
                    "stream": True,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers.get("content-type", "").startswith("text/event-stream"))
        self.assertIn('"object": "image.generation.result"', response.text)
        self.assertIn("https://external.example/image.png", response.text)
        self.assertEqual(len(channels.calls), 1)
        self.assertFalse(channels.internal_pool_checked)
        self.assertEqual(record_calls[0]["channel"], "External")

    def test_admin_stream_edit_uses_external_channel(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        auth.identity = {
            "id": "admin",
            "name": "Admin",
            "role": "admin",
        }
        channels = FakeChannelService()
        channels.edit_result = (
            {"created": 1, "data": [{"url": "https://external.example/edit.png"}]},
            "External",
        )
        record_calls: list[dict[str, object]] = []

        def fake_record_image_result(identity: dict[str, object], result: dict[str, object], **kwargs: object):
            record_calls.append(dict(kwargs))
            return []

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai, "record_image_result", fake_record_image_result),
        ):
            response = TestClient(app).post(
                "/v1/images/edits",
                headers={"Authorization": "Bearer user-token"},
                data={
                    "model": "gpt-image-2",
                    "prompt": "edit",
                    "n": "1",
                    "response_format": "url",
                    "stream": "true",
                },
                files={"image": ("input.png", b"image-bytes", "image/png")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers.get("content-type", "").startswith("text/event-stream"))
        self.assertIn('"object": "image.generation.result"', response.text)
        self.assertIn("https://external.example/edit.png", response.text)
        self.assertEqual(len(channels.edit_calls), 1)
        self.assertFalse(channels.internal_pool_checked)
        self.assertEqual(record_calls[0]["channel"], "External")

    def test_enabled_personal_channel_failure_does_not_fall_back_to_internal_pool(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        channels = FakeChannelService()
        internal_calls: list[dict[str, object]] = []

        def fake_internal(payload: dict[str, object]):
            internal_calls.append(dict(payload))
            return {"created": 1, "data": [{"url": "https://internal.example/image.png"}]}

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai.openai_v1_image_generations, "handle", fake_internal),
        ):
            response = TestClient(app).post(
                "/v1/images/generations",
                headers={"Authorization": "Bearer user-token"},
                json={
                    "model": "gpt-image-2",
                    "prompt": "draw",
                    "n": 1,
                    "response_format": "url",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("personal image channel failed", response.text)
        self.assertEqual(len(channels.calls), 1)
        self.assertFalse(channels.internal_pool_checked)
        self.assertEqual(internal_calls, [])
        self.assertEqual(auth.reserved, [])
        self.assertEqual(auth.released, [])

    def test_enabled_personal_channel_with_zero_local_quota_skips_reservation(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        auth.reserve_error = ValueError("insufficient image quota")
        channels = FakeChannelService()
        channels.generation_result = (
            {"created": 1, "data": [{"url": "https://personal.example/image.png"}]},
            "个人渠道/Mine",
        )
        record_calls: list[dict[str, object]] = []

        def fake_record_image_result(identity: dict[str, object], result: dict[str, object], **kwargs: object):
            record_calls.append(dict(kwargs))
            return []

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai, "record_image_result", fake_record_image_result),
        ):
            response = TestClient(app).post(
                "/v1/images/generations",
                headers={"Authorization": "Bearer user-token"},
                json={
                    "model": "gpt-image-2",
                    "prompt": "draw",
                    "n": 1,
                    "response_format": "url",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"][0]["url"], "https://personal.example/image.png")
        self.assertEqual(auth.reserved, [])
        self.assertEqual(auth.released, [])
        self.assertEqual(len(channels.calls), 1)
        self.assertEqual(record_calls[0]["channel"], "个人渠道/Mine")
        self.assertEqual(record_calls[0]["quota_cost"], 0)

    def test_enabled_personal_edit_channel_with_zero_local_quota_skips_reservation(self) -> None:
        app = FastAPI()
        app.include_router(api_ai.create_router())
        auth = FakeAuthService()
        auth.reserve_error = ValueError("insufficient image quota")
        channels = FakeChannelService()
        channels.edit_result = (
            {"created": 1, "data": [{"url": "https://personal.example/edit.png"}]},
            "个人渠道/Mine",
        )
        record_calls: list[dict[str, object]] = []

        def fake_record_image_result(identity: dict[str, object], result: dict[str, object], **kwargs: object):
            record_calls.append(dict(kwargs))
            return []

        with (
            mock.patch.object(api_support, "auth_service", auth),
            mock.patch.object(api_ai, "auth_service", auth),
            mock.patch.object(api_ai, "channel_service", channels),
            mock.patch.object(api_ai, "record_image_result", fake_record_image_result),
        ):
            response = TestClient(app).post(
                "/v1/images/edits",
                headers={"Authorization": "Bearer user-token"},
                data={
                    "model": "gpt-image-2",
                    "prompt": "edit",
                    "n": "1",
                    "response_format": "url",
                },
                files={"image": ("input.png", b"image-bytes", "image/png")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"][0]["url"], "https://personal.example/edit.png")
        self.assertEqual(auth.reserved, [])
        self.assertEqual(auth.released, [])
        self.assertEqual(len(channels.edit_calls), 1)
        self.assertEqual(record_calls[0]["channel"], "个人渠道/Mine")
        self.assertEqual(record_calls[0]["quota_cost"], 0)


if __name__ == "__main__":
    unittest.main()
