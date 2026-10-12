import unittest

from pr_watcher.close_finished_issues import (
    CLOSED,
    FAILED,
    MERGED,
    OPEN,
    Outcome,
    TrackedIssue,
    close_finished_issues,
    fetch_tracked_issues,
    format_summary,
    llvm_pr_number,
)
from pr_watcher.github_api import GitHubError


class FakeClient:
    """Serves pull requests and issues, and records what was written."""

    def __init__(self, pulls=None, issues=None, fail_paths=()):
        self.pulls = pulls or {}
        self.issues = issues or []
        self.fail_paths = set(fail_paths)
        self.gets = []
        self.writes = []

    def get(self, path, params=None):
        self.gets.append(path)
        if path in self.fail_paths:
            raise GitHubError(f"boom on {path}")
        return self.pulls[int(path.rsplit("/", 1)[1])]

    def paginate(self, path, params=None, items_key=None):
        return self.issues

    def post(self, path, payload):
        self.writes.append(("POST", path, payload))

    def patch(self, path, payload):
        if path in self.fail_paths:
            raise GitHubError(f"boom on {path}")
        self.writes.append(("PATCH", path, payload))


def _pull(state="open", merged_at=None):
    return {"state": state, "merged_at": merged_at}


def _issue_payload(number, body, labels=("test-cpp",), pull_request=False):
    payload = {
        "number": number,
        "body": body,
        "labels": [{"name": label} for label in labels],
    }
    if pull_request:
        payload["pull_request"] = {}
    return payload


class TestLlvmPrNumber(unittest.TestCase):
    def test_reads_the_pull_request_on_the_first_line(self):
        body = "https://github.com/llvm/llvm-project/pull/181570 bugprone-x\n\nnotes"
        self.assertEqual(llvm_pr_number(body), 181570)

    def test_accepts_a_trailing_slash(self):
        self.assertEqual(
            llvm_pr_number("https://github.com/llvm/llvm-project/pull/1/ check"), 1
        )

    def test_ignores_other_repositories(self):
        self.assertIsNone(llvm_pr_number("https://github.com/org/repo/pull/1 check"))

    def test_ignores_issues_without_a_pull_request(self):
        self.assertIsNone(llvm_pr_number("bugprone-x"))
        self.assertIsNone(llvm_pr_number(""))
        self.assertIsNone(llvm_pr_number("Scaling CTIT runs: some thoughts"))


class TestFetchTrackedIssues(unittest.TestCase):
    def test_keeps_labelled_issues_that_link_an_llvm_pull_request(self):
        pr = "https://github.com/llvm/llvm-project/pull/{} check"
        client = FakeClient(
            issues=[
                _issue_payload(1, pr.format(10)),
                _issue_payload(2, pr.format(20), labels=("test-c",)),
                _issue_payload(3, pr.format(30), labels=("question",)),
                _issue_payload(4, "readability-x"),
                _issue_payload(5, pr.format(50), pull_request=True),
                _issue_payload(6, None),
            ]
        )
        self.assertEqual(
            fetch_tracked_issues(client, "org/ctit"),
            [TrackedIssue(1, 10), TrackedIssue(2, 20)],
        )


class TestCloseFinishedIssues(unittest.TestCase):
    def test_closes_issues_of_merged_and_closed_pull_requests(self):
        client = FakeClient(
            pulls={
                10: _pull("closed", "2026-10-01T00:00:00Z"),
                20: _pull("closed"),
                30: _pull("open"),
            }
        )
        issues = [TrackedIssue(1, 10), TrackedIssue(2, 20), TrackedIssue(3, 30)]

        outcomes = close_finished_issues(client, "org/ctit", issues, dry_run=False)

        self.assertEqual([o.kind for o in outcomes], [MERGED, CLOSED, OPEN])
        self.assertEqual(
            client.writes,
            [
                (
                    "POST",
                    "repos/org/ctit/issues/1/comments",
                    {
                        "body": "Closing: https://github.com/llvm/llvm-project/pull/10"
                        " was merged."
                    },
                ),
                (
                    "PATCH",
                    "repos/org/ctit/issues/1",
                    {"state": "closed", "state_reason": "completed"},
                ),
                (
                    "POST",
                    "repos/org/ctit/issues/2/comments",
                    {
                        "body": "Closing: https://github.com/llvm/llvm-project/pull/20"
                        " was closed without merging."
                    },
                ),
                (
                    "PATCH",
                    "repos/org/ctit/issues/2",
                    {"state": "closed", "state_reason": "not_planned"},
                ),
            ],
        )

    def test_dry_run_writes_nothing(self):
        client = FakeClient(pulls={10: _pull("closed", "2026-10-01T00:00:00Z")})
        outcomes = close_finished_issues(
            client, "org/ctit", [TrackedIssue(1, 10)], dry_run=True
        )
        self.assertEqual(outcomes[0].kind, MERGED)
        self.assertEqual(client.writes, [])

    def test_looks_up_each_pull_request_once(self):
        client = FakeClient(pulls={10: _pull("closed")})
        close_finished_issues(
            client,
            "org/ctit",
            [TrackedIssue(1, 10), TrackedIssue(2, 10)],
            dry_run=False,
        )
        self.assertEqual(client.gets, ["repos/llvm/llvm-project/pulls/10"])
        closed = [path for method, path, _ in client.writes if method == "PATCH"]
        self.assertEqual(closed, ["repos/org/ctit/issues/1", "repos/org/ctit/issues/2"])

    def test_one_failure_does_not_stop_the_rest(self):
        client = FakeClient(
            pulls={20: _pull("closed")},
            fail_paths={"repos/llvm/llvm-project/pulls/10"},
        )
        outcomes = close_finished_issues(
            client,
            "org/ctit",
            [TrackedIssue(1, 10), TrackedIssue(2, 20)],
            dry_run=False,
        )
        self.assertEqual([o.kind for o in outcomes], [FAILED, CLOSED])
        self.assertIn("boom", outcomes[0].detail)


class TestFormatSummary(unittest.TestCase):
    def test_lists_closed_issues_and_failures(self):
        summary = format_summary(
            [
                close_outcome(1, 10, MERGED),
                close_outcome(2, 20, OPEN),
                close_outcome(3, 30, FAILED, "502 | bad gateway"),
            ],
            dry_run=False,
        )
        self.assertIn(
            "| #1 | [llvm#10](https://github.com/llvm/llvm-project/pull/10) | closed, PR merged |",
            summary,
        )
        self.assertIn("failed: 502 \\| bad gateway", summary)
        self.assertNotIn("#2 ", summary)
        self.assertIn("**Closed 1 of 3 open test issue(s).**", summary)

    def test_dry_run_says_would_close(self):
        summary = format_summary([close_outcome(1, 10, CLOSED)], dry_run=True)
        self.assertIn("would close, PR closed", summary)
        self.assertIn("**Would close 1 of 1 open test issue(s).**", summary)

    def test_nothing_to_close(self):
        summary = format_summary([close_outcome(1, 10, OPEN)], dry_run=False)
        self.assertIn("All 1 open test issues track an open pull request", summary)


def close_outcome(number, pr_number, kind, detail=""):
    return Outcome(TrackedIssue(number, pr_number), kind, detail)


if __name__ == "__main__":
    unittest.main()
