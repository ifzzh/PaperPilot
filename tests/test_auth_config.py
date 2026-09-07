import unittest

from paperpilot.auth import AuthConfig, AuthConfigurationError


class TestAuthConfig(unittest.TestCase):
    def test_secure_defaults_require_complete_supabase_configuration(self):
        with self.assertRaisesRegex(AuthConfigurationError, "SUPABASE_URL"):
            AuthConfig.from_environ({})

    def test_partial_supabase_configuration_is_rejected(self):
        with self.assertRaisesRegex(AuthConfigurationError, "SUPABASE_ANON_KEY"):
            AuthConfig.from_environ(
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "PAPERPILOT_ALLOWED_EMAILS": "admin@example.com",
                }
            )

    def test_production_cannot_disable_authentication(self):
        with self.assertRaisesRegex(AuthConfigurationError, "production"):
            AuthConfig.from_environ(
                {
                    "PAPERPILOT_ENV": "production",
                    "PAPERPILOT_AUTH_MODE": "disabled",
                }
            )

    def test_development_can_explicitly_disable_authentication(self):
        config = AuthConfig.from_environ(
            {
                "PAPERPILOT_ENV": "development",
                "PAPERPILOT_AUTH_MODE": "disabled",
                "PAPERPILOT_COOKIE_SECURE": "false",
            }
        )

        self.assertFalse(config.enabled)
        self.assertFalse(config.cookie_secure)

    def test_allowed_emails_are_normalized(self):
        config = AuthConfig.from_environ(
            {
                "PAPERPILOT_ENV": "production",
                "PAPERPILOT_AUTH_MODE": "supabase",
                "SUPABASE_URL": "https://example.supabase.co/",
                "SUPABASE_ANON_KEY": "public-key",
                "PAPERPILOT_ALLOWED_EMAILS": " Admin@Example.com,other@example.com ",
            }
        )

        self.assertEqual(config.supabase_url, "https://example.supabase.co")
        self.assertEqual(
            config.allowed_emails,
            frozenset({"admin@example.com", "other@example.com"}),
        )
        self.assertTrue(config.cookie_secure)

    def test_invalid_boolean_is_rejected(self):
        with self.assertRaisesRegex(AuthConfigurationError, "true or false"):
            AuthConfig.from_environ(
                {
                    "PAPERPILOT_ENV": "development",
                    "PAPERPILOT_AUTH_MODE": "disabled",
                    "PAPERPILOT_COOKIE_SECURE": "sometimes",
                }
            )


if __name__ == "__main__":
    unittest.main()
