import unittest

import app as app_module

from paperpilot.auth import AuthConfig


class TestBrowserSecurityHeaders(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        app_module.AUTH_CONFIG = AuthConfig.from_environ(
            {
                "PAPERPILOT_ENV": "production",
                "PAPERPILOT_AUTH_MODE": "local",
            }
        )
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.AUTH_CONFIG = None

    def test_security_headers_cover_public_static_viewer_and_api_responses(self):
        responses = [
            self.client.get("/"),
            self.client.get("/healthz"),
            self.client.get("/static/js/content_security.js"),
            self.client.get("/viewer/example"),
            self.client.get("/viewer/analysis/example"),
            self.client.get("/api/paper/example"),
        ]

        for response in responses:
            with self.subTest(path=response.request.path):
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
                self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
                self.assertEqual(
                    response.headers["Permissions-Policy"],
                    "camera=(), microphone=(), geolocation=()",
                )
                self.assertIn("Content-Security-Policy", response.headers)
                self.assertNotIn("Content-Security-Policy-Report-Only", response.headers)

    def test_enforced_policy_allows_only_self_hosted_scripts(self):
        response = self.client.get("/")
        policy = response.headers["Content-Security-Policy"]

        for directive in (
            "default-src 'self'",
            "object-src 'none'",
            "frame-ancestors 'self'",
            "script-src 'self'",
            "script-src-attr 'none'",
            "style-src 'self' 'unsafe-inline'",
            "worker-src 'self' blob:",
            "connect-src 'self'",
        ):
            self.assertIn(directive, policy)
        for forbidden in (
            "unsafe-eval",
            "script-src 'self' 'unsafe-inline'",
            "cdnjs.cloudflare.com",
            "cdn.jsdelivr.net",
            "unpkg.com",
            "cdn.bootcdn.net",
            "supabase",
        ):
            self.assertNotIn(forbidden, policy.lower())


if __name__ == "__main__":
    unittest.main()
