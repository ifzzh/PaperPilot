import unittest

from paperpilot.auth import AuthConfig, AuthConfigurationError


class TestAuthConfig(unittest.TestCase):
    def test_secure_defaults_use_local_authentication(self):
        config = AuthConfig.from_environ({})
        self.assertTrue(config.enabled)
        self.assertEqual(config.mode, "local")
        self.assertTrue(config.cookie_secure)

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

    def test_production_local_authentication_is_enabled(self):
        config = AuthConfig.from_environ(
            {
                "PAPERPILOT_ENV": "production",
                "PAPERPILOT_AUTH_MODE": "local",
            }
        )
        self.assertTrue(config.enabled)
        self.assertTrue(config.cookie_secure)

    def test_supabase_mode_is_rejected(self):
        with self.assertRaisesRegex(AuthConfigurationError, "local or disabled"):
            AuthConfig.from_environ({"PAPERPILOT_AUTH_MODE": "supabase"})

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
