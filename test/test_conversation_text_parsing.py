from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from services.protocol.conversation import (
    ConversationRequest,
    ImageGenerationError,
    assistant_message_text,
    format_image_result,
    iter_conversation_payloads,
    stream_image_outputs,
    stream_image_outputs_with_pool,
)


class ConversationTextParsingTests(unittest.TestCase):
    def test_assistant_message_text_reads_object_parts(self) -> None:
        message = {
            "author": {"role": "assistant"},
            "content": {
                "content_type": "text",
                "parts": [
                    {"type": "text", "text": "你好"},
                    {"content_type": "text", "text": "，有什么可以帮你？"},
                ],
            },
        }

        self.assertEqual(assistant_message_text(message), "你好，有什么可以帮你？")

    def test_iter_payloads_reads_nested_text_patch_path(self) -> None:
        payloads = iter([
            json.dumps({"p": "/message/content/parts/0/text", "o": "append", "v": "你"}, ensure_ascii=False),
            json.dumps({"p": "/message/content/parts/0/text", "o": "append", "v": "好"}, ensure_ascii=False),
            "[DONE]",
        ])

        events = list(iter_conversation_payloads(payloads))
        deltas = [event.get("delta") for event in events if event.get("type") == "conversation.delta"]

        self.assertEqual(deltas, ["你", "好"])

    def test_iter_payloads_reads_deep_text_patch_path(self) -> None:
        payloads = iter([
            json.dumps({"p": "/message/content/parts/0/content/text", "o": "append", "v": "深层文本"}, ensure_ascii=False),
            "[DONE]",
        ])

        events = list(iter_conversation_payloads(payloads))
        deltas = [event.get("delta") for event in events if event.get("type") == "conversation.delta"]

        self.assertEqual(deltas, ["深层文本"])

    def test_iter_payloads_reads_append_operation_without_path(self) -> None:
        payloads = iter([
            json.dumps({"o": "append", "v": "无路径文本"}, ensure_ascii=False),
            "[DONE]",
        ])

        events = list(iter_conversation_payloads(payloads))
        deltas = [event.get("delta") for event in events if event.get("type") == "conversation.delta"]

        self.assertEqual(deltas, ["无路径文本"])

    def test_iter_payloads_reads_message_carried_directly_in_v(self) -> None:
        payloads = iter([
            json.dumps({
                "v": {
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": [{"text": "可以正常输出"}]},
                },
            }, ensure_ascii=False),
            "[DONE]",
        ])

        events = list(iter_conversation_payloads(payloads))
        deltas = [event.get("delta") for event in events if event.get("type") == "conversation.delta"]

        self.assertEqual(deltas, ["可以正常输出"])

    def test_iter_payloads_ignores_image_tool_argument_text(self) -> None:
        payloads = iter([
            json.dumps({
                "v": json.dumps({
                    "prompt": None,
                    "size": "1024x1024",
                    "n": 1,
                    "referenced_image_ids": ["file_00000000000000000000000000000000"],
                })
            }),
            "[DONE]",
        ])

        events = list(iter_conversation_payloads(payloads))
        deltas = [event.get("delta") for event in events if event.get("type") == "conversation.delta"]

        self.assertEqual(deltas, [])

    def test_format_image_result_defaults_to_url_without_base64(self) -> None:
        with patch("services.protocol.conversation.save_image_bytes", return_value="http://local/images/generated.png"):
            result = format_image_result([{"image_data": b"image-bytes"}], "draw", "url")

        self.assertEqual(result["data"][0]["url"], "http://local/images/generated.png")
        self.assertNotIn("b64_json", result["data"][0])

    def test_format_image_result_preserves_explicit_base64_response(self) -> None:
        with patch("services.protocol.conversation.save_image_bytes", return_value="http://local/images/generated.png"):
            result = format_image_result([{"image_data": b"image-bytes"}], "draw", "b64_json")

        self.assertEqual(result["data"][0]["url"], "http://local/images/generated.png")
        self.assertEqual(result["data"][0]["b64_json"], "aW1hZ2UtYnl0ZXM=")

    def test_format_image_result_uses_webdav_direct_upload_when_identity_present(self) -> None:
        with (
            patch(
                "services.webdav_service.upload_generated_image_bytes",
                return_value={
                    "url": "https://cdn.example/YanAI/generated.png",
                    "synced_at": "2026-06-05 20:00:00",
                },
            ) as upload,
            patch("services.protocol.conversation.save_image_bytes") as save_image,
        ):
            result = format_image_result(
                [{"image_data": b"image-bytes"}],
                "draw",
                "url",
                storage_identity={"id": "admin", "role": "admin"},
            )

        upload.assert_called_once_with({"id": "admin", "role": "admin"}, b"image-bytes")
        save_image.assert_not_called()
        self.assertEqual(result["data"][0]["url"], "https://cdn.example/YanAI/generated.png")
        self.assertEqual(result["data"][0]["webdav_url"], "https://cdn.example/YanAI/generated.png")
        self.assertEqual(result["data"][0]["webdav_status"], "synced")
        self.assertEqual(result["data"][0]["webdav_synced_at"], "2026-06-05 20:00:00")
        self.assertNotIn("b64_json", result["data"][0])

    def test_image_stream_polls_prepared_conversation_after_skipped_mainline(self) -> None:
        class FakeBackend:
            resolved_conversation_id = ""

            def stream_conversation(self, **kwargs):
                yield json.dumps({"type": "image_prepare", "conversation_id": "conv-prepared"})
                yield json.dumps({"skipped_mainline": True}, separators=(",", ":"))
                yield "[DONE]"

            def resolve_conversation_image_urls(self, conversation_id, file_ids, sediment_ids):
                self.resolved_conversation_id = conversation_id
                return ["https://example.test/generated.png"] if conversation_id == "conv-prepared" else []

            def download_image_bytes(self, urls):
                return [b"image-bytes"]

        backend = FakeBackend()
        with patch("services.protocol.conversation.save_image_bytes", return_value="http://local/images/generated.png"):
            outputs = list(stream_image_outputs(backend, ConversationRequest(prompt="draw", model="gpt-image-2")))

        results = [output for output in outputs if output.kind == "result"]
        self.assertEqual(backend.resolved_conversation_id, "conv-prepared")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].data[0]["url"], "http://local/images/generated.png")
        self.assertNotIn("b64_json", results[0].data[0])

    def test_image_stream_polls_when_image_gen_reports_tool_not_invoked(self) -> None:
        class FakeBackend:
            resolved_conversation_id = ""

            def stream_conversation(self, **kwargs):
                yield json.dumps({"type": "image_prepare", "conversation_id": "conv-prepared"})
                yield json.dumps({
                    "v": {
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {"content_type": "text", "parts": ["图片生成中"]},
                        },
                        "conversation_id": "conv-prepared",
                    }
                }, ensure_ascii=False)
                yield json.dumps({
                    "type": "server_ste_metadata",
                    "conversation_id": "conv-prepared",
                    "metadata": {"tool_invoked": False, "turn_use_case": "image gen"},
                })
                yield "[DONE]"

            def resolve_conversation_image_urls(self, conversation_id, file_ids, sediment_ids):
                self.resolved_conversation_id = conversation_id
                return ["https://example.test/generated.png"] if conversation_id == "conv-prepared" else []

            def download_image_bytes(self, urls):
                return [b"image-bytes"]

        backend = FakeBackend()
        with patch("services.protocol.conversation.save_image_bytes", return_value="http://local/images/generated.png"):
            outputs = list(stream_image_outputs(backend, ConversationRequest(prompt="draw", model="gpt-image-2")))

        results = [output for output in outputs if output.kind == "result"]
        self.assertEqual(backend.resolved_conversation_id, "conv-prepared")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].data[0]["url"], "http://local/images/generated.png")
        self.assertNotIn("b64_json", results[0].data[0])

    def test_image_stream_times_out_without_result_or_message(self) -> None:
        class FakeBackend:
            def stream_conversation(self, **kwargs):
                yield json.dumps({"type": "image_prepare", "conversation_id": "conv-prepared"})
                yield json.dumps({
                    "v": json.dumps({
                        "prompt": None,
                        "size": "1024x1024",
                        "n": 1,
                        "referenced_image_ids": ["file_00000000000000000000000000000000"],
                    })
                })
                yield "[DONE]"

            def resolve_conversation_image_urls(self, conversation_id, file_ids, sediment_ids):
                return []

        with self.assertRaises(ImageGenerationError) as raised:
            list(stream_image_outputs(FakeBackend(), ConversationRequest(prompt="draw", model="gpt-image-2")))

        self.assertEqual(raised.exception.code, "image_generation_timeout")
        self.assertIn("conversation_id=conv-prepared", str(raised.exception))

    def test_image_pool_removes_revoked_token_after_progress_and_retries(self) -> None:
        class FakeLease:
            def __init__(self, access_token: str) -> None:
                self.access_token = access_token
                self.lease_owner = "request-1"
                self.account = {"access_token": access_token}

        class FakeAccountService:
            def __init__(self) -> None:
                self.tokens = ["revoked-token", "good-token"]
                self.removed: list[tuple[str, str]] = []

            def lease_available_account(self, lease_owner=None):
                if not self.tokens:
                    raise RuntimeError("no available image quota")
                return FakeLease(self.tokens.pop(0))

            def release_image_account(self, lease, success=None):
                return {}

            def remove_invalid_token(self, access_token, event):
                self.removed.append((access_token, event))
                return True

            def update_account(self, access_token, updates):
                return {}

        class FakeBackend:
            def __init__(self, access_token: str) -> None:
                self.access_token = access_token

            def stream_conversation(self, **kwargs):
                yield json.dumps({"type": "image_prepare", "conversation_id": f"conv-{self.access_token}"})
                yield "[DONE]"

            def resolve_conversation_image_urls(self, conversation_id, file_ids, sediment_ids):
                if self.access_token == "revoked-token":
                    raise RuntimeError(
                        "/backend-api/conversation/conv-revoked failed: status=401, "
                        "body={'error': {'code': 'token_revoked'}}"
                    )
                return ["https://example.test/generated.png"]

            def download_image_bytes(self, urls):
                return [b"image-bytes"]

        fake_account_service = FakeAccountService()
        with (
            patch("services.protocol.conversation.account_service", fake_account_service),
            patch("services.protocol.conversation.OpenAIBackendAPI", FakeBackend),
            patch("services.protocol.conversation.save_image_bytes", return_value="http://local/images/generated.png"),
        ):
            outputs = list(stream_image_outputs_with_pool(ConversationRequest(prompt="draw", model="gpt-image-2")))

        results = [output for output in outputs if output.kind == "result"]
        self.assertEqual(fake_account_service.removed, [("revoked-token", "image_stream")])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].data[0]["url"], "http://local/images/generated.png")
        self.assertNotIn("b64_json", results[0].data[0])


if __name__ == "__main__":
    unittest.main()
