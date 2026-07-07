from __future__ import annotations

import unittest

from services.protocol.openai_v1_response import image_output_items
from utils.helper import build_chat_image_markdown_content


class ProtocolImageUrlOutputTests(unittest.TestCase):
    def test_chat_markdown_prefers_url_over_base64(self) -> None:
        content = build_chat_image_markdown_content({
            "data": [{
                "url": "http://local/images/generated.png",
                "b64_json": "aW1hZ2U=",
            }]
        })

        self.assertEqual(content, "![image_1](http://local/images/generated.png)")

    def test_responses_image_item_uses_url_result(self) -> None:
        items = image_output_items("draw", [{
            "url": "http://local/images/generated.png",
            "b64_json": "aW1hZ2U=",
        }])

        self.assertEqual(items[0]["result"], "http://local/images/generated.png")
        self.assertEqual(items[0]["url"], "http://local/images/generated.png")


if __name__ == "__main__":
    unittest.main()
