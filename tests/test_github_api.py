import email.message
import io
import unittest
import urllib.error
from unittest.mock import patch

from pr_watch.github_api import MAX_ATTEMPTS, GitHubClient, GitHubError


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.test/x", code, "boom", email.message.Message(), io.BytesIO(b"{}")
    )


class TestGitHubClientRetries(unittest.TestCase):
    """A retried POST would open the same issue twice, so only safe calls repeat."""

    def _attempts(self, method: str, error: Exception) -> int:
        calls: list[str] = []

        def fake_urlopen(request, timeout=None):
            calls.append(request.get_method())
            raise error

        with (
            patch("pr_watch.github_api.urllib.request.urlopen", fake_urlopen),
            patch("pr_watch.github_api.time.sleep"),
        ):
            client = GitHubClient("token")
            with self.assertRaises(GitHubError):
                if method == "GET":
                    client.get("x")
                else:
                    client.post("x", {})
        return len(calls)

    def test_retries_get_on_server_error(self):
        self.assertEqual(self._attempts("GET", _http_error(502)), MAX_ATTEMPTS)

    def test_does_not_retry_post_on_server_error(self):
        self.assertEqual(self._attempts("POST", _http_error(502)), 1)

    def test_does_not_retry_post_on_dropped_connection(self):
        self.assertEqual(self._attempts("POST", urllib.error.URLError("timed out")), 1)

    def test_retries_get_on_dropped_connection(self):
        self.assertEqual(
            self._attempts("GET", urllib.error.URLError("timed out")), MAX_ATTEMPTS
        )

    def test_retries_post_on_rate_limit(self):
        self.assertEqual(self._attempts("POST", _http_error(429)), MAX_ATTEMPTS)

    def test_does_not_retry_a_rejected_request(self):
        self.assertEqual(self._attempts("GET", _http_error(404)), 1)

    def test_reports_the_status_in_the_error(self):
        with patch("pr_watch.github_api.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = _http_error(404)
            with self.assertRaises(GitHubError) as caught:
                GitHubClient("token").get("x")
        self.assertIn("404", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
