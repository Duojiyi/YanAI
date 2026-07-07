from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest import mock

from api import register as register_api


class RegisterEventsAuthTests(unittest.TestCase):
    def test_events_endpoint_uses_authorization_header_not_query_token(self) -> None:
        router = register_api.create_router()
        endpoint = next(
            route.endpoint
            for route in router.routes
            if getattr(route, "path", "") == "/api/register/events"
        )
        signature = inspect.signature(endpoint)

        self.assertIn("authorization", signature.parameters)
        self.assertNotIn("token", signature.parameters)

        seen_authorizations: list[str | None] = []

        def fake_require_admin(authorization: str | None):
            seen_authorizations.append(authorization)
            return {"id": "admin", "role": "admin"}

        with mock.patch.object(register_api, "require_admin", fake_require_admin):
            response = asyncio.run(endpoint(authorization="Bearer header-token"))

        self.assertEqual(seen_authorizations, ["Bearer header-token"])
        self.assertEqual(response.media_type, "text/event-stream")


if __name__ == "__main__":
    unittest.main()
