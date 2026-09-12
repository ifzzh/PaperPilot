import unittest

from ipaper.auth import FixedWindowRateLimiter


class TestFixedWindowRateLimiter(unittest.TestCase):
    def test_rejects_after_limit_and_reports_retry_after(self):
        limiter = FixedWindowRateLimiter()
        self.assertTrue(
            limiter.check("auth", "127.0.0.1", limit=2, window_seconds=10, now=1).allowed
        )
        self.assertTrue(
            limiter.check("auth", "127.0.0.1", limit=2, window_seconds=10, now=2).allowed
        )
        rejected = limiter.check(
            "auth", "127.0.0.1", limit=2, window_seconds=10, now=3
        )
        self.assertFalse(rejected.allowed)
        self.assertEqual(rejected.retry_after, 8)

    def test_window_expiry_allows_new_request(self):
        limiter = FixedWindowRateLimiter()
        limiter.check("auth", "user", limit=1, window_seconds=10, now=1)
        result = limiter.check("auth", "user", limit=1, window_seconds=10, now=11)
        self.assertTrue(result.allowed)

    def test_buckets_and_identities_are_isolated(self):
        limiter = FixedWindowRateLimiter()
        limiter.check("ai", "one", limit=1, window_seconds=10, now=1)
        self.assertTrue(
            limiter.check("ai", "two", limit=1, window_seconds=10, now=2).allowed
        )
        self.assertTrue(
            limiter.check("upload", "one", limit=1, window_seconds=10, now=2).allowed
        )


if __name__ == "__main__":
    unittest.main()
