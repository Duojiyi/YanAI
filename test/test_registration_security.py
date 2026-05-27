import unittest
from unittest import mock

from services.config import config
from services import registration_security


class RegistrationSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_config = dict(config.data)
        registration_security.clear_verification_codes()

    def tearDown(self) -> None:
        config.data = self._old_config
        registration_security.clear_verification_codes()

    def test_email_domain_whitelist_allows_exact_and_wildcard_domains(self) -> None:
        config.data.update(
            {
                "email_domain_whitelist_enabled": True,
                "email_domain_whitelist": ["example.com", "*.trusted.test"],
            }
        )

        self.assertEqual(registration_security.validate_registration_email("USER@example.com"), "user@example.com")
        self.assertEqual(
            registration_security.validate_registration_email("user@team.trusted.test"),
            "user@team.trusted.test",
        )
        with self.assertRaisesRegex(ValueError, "domain"):
            registration_security.validate_registration_email("user@blocked.test")

    def test_email_alias_restriction_blocks_plus_and_gmail_dot_aliases(self) -> None:
        config.data.update({"email_alias_restriction_enabled": True})

        with self.assertRaisesRegex(ValueError, "aliases"):
            registration_security.validate_registration_email("user+tag@example.com")
        with self.assertRaisesRegex(ValueError, "gmail"):
            registration_security.validate_registration_email("first.last@gmail.com")

    def test_registration_code_can_be_verified_once(self) -> None:
        config.data.update(
            {
                "email_verification_enabled": True,
                "email_domain_whitelist_enabled": False,
                "email_alias_restriction_enabled": False,
                "smtp_host": "smtp.example.com",
                "smtp_from_email": "notice@example.com",
            }
        )

        with mock.patch.object(registration_security.secrets, "randbelow", return_value=123456):
            with mock.patch.object(registration_security, "_send_email") as send_email:
                registration_security.send_registration_verification_code("user@example.com")

        send_email.assert_called_once()
        registration_security.verify_registration_code("user@example.com", "123456")
        with self.assertRaisesRegex(ValueError, "invalid or expired"):
            registration_security.verify_registration_code("user@example.com", "123456")


if __name__ == "__main__":
    unittest.main()
