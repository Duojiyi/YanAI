from copy import deepcopy
import unittest
from unittest import mock

from services.register import mail_provider, openai_register


class OpenAIRegisterTests(unittest.TestCase):
    def test_mailbox_creation_receives_registration_proxy(self) -> None:
        saved_config = deepcopy(openai_register.config)
        try:
            openai_register.config.update({
                "proxy": "http://127.0.0.1:3067",
                "mail": {"providers": [{"type": "gptmail", "enable": True, "api_key": "key"}]},
            })

            with mock.patch.object(openai_register.mail_provider, "create_mailbox", return_value={"address": "user@example.com"}) as create_mailbox:
                openai_register.create_mailbox()

            self.assertEqual(create_mailbox.call_args.args[0]["proxy"], "http://127.0.0.1:3067")
        finally:
            openai_register.config.clear()
            openai_register.config.update(saved_config)

    def test_add_registered_account_preserves_oauth_credentials(self) -> None:
        saved_items = []

        class FakeAccountService:
            def add_account_items(self, items):
                saved_items.extend(items)

        result = {
            "email": "user@example.com",
            "password": "password-value",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "id-token",
            "created_at": "2026-05-26T00:00:00+00:00",
        }

        with mock.patch.object(openai_register, "account_service", FakeAccountService()):
            openai_register._add_registered_account(result)

        self.assertEqual(
            saved_items,
            [
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "id_token": "id-token",
                    "email": "user@example.com",
                    "password": "password-value",
                    "created_at": "2026-05-26T00:00:00+00:00",
                }
            ],
        )


class MailProviderProxyTests(unittest.TestCase):
    def test_gptmail_uses_configured_proxy(self) -> None:
        provider = mail_provider.GptMailProvider(
            {"api_key": "key"},
            {
                "request_timeout": 15,
                "wait_timeout": 30,
                "wait_interval": 3,
                "user_agent": "Mozilla/5.0",
                "proxy": "http://127.0.0.1:3067",
            },
        )
        try:
            self.assertEqual(provider.session.proxies["http"], "http://127.0.0.1:3067")
            self.assertEqual(provider.session.proxies["https"], "http://127.0.0.1:3067")
        finally:
            provider.close()


if __name__ == "__main__":
    unittest.main()
