import unittest

from crash_detection.post_check_timings import (
    TimingsRecord,
    build_comment,
    create_tracking_issue,
    fetch_latest_record,
    find_tracking_issue,
    format_change,
    format_marker,
    notable_changes,
    parse_comment,
)
from pr_watcher.github_api import GitHubError

OLD_LLVM = "1111111111111111111111111111111111111111"
NEW_LLVM = "2222222222222222222222222222222222222222"
PREVIOUS_URL = "https://github.com/org/repo/issues/7#issuecomment-1"
RUN_URL = "https://github.com/org/repo/actions/runs/1"


def _record(timings, date="2026-10-08", llvm=NEW_LLVM, runner="arm-1", url=None):
    return TimingsRecord(
        date=date, llvm_revision=llvm, runner=runner, timings=timings, url=url
    )


def _previous(timings, **kwargs):
    kwargs.setdefault("date", "2026-10-07")
    kwargs.setdefault("llvm", OLD_LLVM)
    kwargs.setdefault("url", PREVIOUS_URL)
    return _record(timings, **kwargs)


def _comment(previous, current):
    return build_comment(current, "Linux aarch64, 80 CPUs", RUN_URL, previous)


class TestRoundTrip(unittest.TestCase):
    def test_comment_reads_back_as_the_same_record(self):
        current = _record({"check-a": 120.5, "check-b": 0.0, "check-c": 3.25})
        parsed = parse_comment(_comment(None, current), PREVIOUS_URL)
        self.assertEqual(parsed, _record(current.timings, url=PREVIOUS_URL))

    def test_reads_only_the_table_of_all_checks(self):
        # The changes table also starts with a check name and a number.
        previous = _previous({"check-a": 100.0, "check-b": 50.0})
        current = _record({"check-a": 200.0})
        parsed = parse_comment(_comment(previous, current))
        self.assertEqual(parsed.timings, {"check-a": 200.0})

    def test_ignores_comments_without_marker(self):
        self.assertIsNone(parse_comment("| `check-a` | 1.00 | 100.0% | - |"))

    def test_ignores_marker_with_broken_metadata(self):
        body = _comment(None, _record({"check-a": 1.0}))
        body = body.replace('{"date"', "{date", 1)
        self.assertIsNone(parse_comment(body))

    def test_ignores_marker_without_timings(self):
        self.assertIsNone(parse_comment(format_marker(_record({"check-a": 1.0}))))

    def test_drops_malformed_metadata_values(self):
        record = _record({"check-a": 1.0}, date="soon", llvm="main", runner="a`b\nc")
        parsed = parse_comment(_comment(None, record))
        self.assertEqual(parsed.date, "previous run")
        self.assertEqual(parsed.llvm_revision, "")
        self.assertEqual(parsed.runner, "a b c")

    def test_runner_name_cannot_close_the_marker(self):
        record = _record({"check-a": 1.0}, runner="x --> y")
        self.assertNotIn("-->", format_marker(record)[:-3])
        self.assertEqual(parse_comment(_comment(None, record)).runner, "x --> y")


class TestFormatChange(unittest.TestCase):
    def test_signed_seconds_and_percent(self):
        self.assertEqual(format_change(200.0, 150.0), "-50.00 (-25.0%)")

    def test_new_and_removed(self):
        self.assertEqual(format_change(None, 1.0), "new")
        self.assertEqual(format_change(1.0, None), "removed")

    def test_no_percent_from_zero(self):
        self.assertEqual(format_change(0.0, 2.5), "+2.50")


class TestNotableChanges(unittest.TestCase):
    def test_needs_both_thresholds(self):
        previous = {"small": 20.0, "big": 4000.0, "slow": 100.0}
        current = {"small": 28.0, "big": 4300.0, "slow": 115.0}
        self.assertEqual(notable_changes(previous, current), [("slow", 100.0, 115.0)])

    def test_added_and_removed_checks_are_always_notable(self):
        changes = notable_changes({"gone": 0.5}, {"added": 0.1})
        self.assertEqual(changes, [("gone", 0.5, None), ("added", None, 0.1)])

    def test_biggest_change_first(self):
        previous = {"a": 100.0, "b": 1000.0}
        current = {"a": 150.0, "b": 800.0}
        self.assertEqual(
            [row[0] for row in notable_changes(previous, current)], ["b", "a"]
        )


class TestBuildComment(unittest.TestCase):
    def test_first_comment_has_nothing_to_compare(self):
        body = _comment(None, _record({"check-a": 1.0}))
        self.assertIn("_No earlier timings on this issue to compare with._", body)
        self.assertIn("| `check-a` | 1.00 | 100.0% | - |", body)
        self.assertNotIn("Changes since", body)

    def test_header_lists_runner_llvm_and_run(self):
        body = _comment(None, _record({"check-a": 1.0}))
        self.assertIn("## Check timings: 2026-10-08", body)
        self.assertIn("- **Runner:** `arm-1` (Linux aarch64, 80 CPUs)", body)
        self.assertIn(f"[`{NEW_LLVM[:12]}`](", body)
        self.assertIn(f"- **Workflow run:** {RUN_URL}", body)

    def test_compares_with_previous_comment(self):
        previous = _previous({"check-a": 100.0, "check-b": 10.0})
        body = _comment(previous, _record({"check-a": 150.0, "check-b": 10.0}))
        self.assertIn(f"### Changes since [2026-10-07]({PREVIOUS_URL})", body)
        self.assertIn("| `check-a` | 100.00 | 150.00 | +50.00 (+50.0%) |", body)
        self.assertIn("| `check-a` | 150.00 | 93.8% | +50.00 (+50.0%) |", body)
        self.assertIn("160.00 s (+50.00 s, +45.5% vs [2026-10-07]", body)
        self.assertIn(f"compare/{OLD_LLVM}...{NEW_LLVM}", body)

    def test_reports_quiet_day(self):
        previous = _previous({"check-a": 100.0}, llvm=NEW_LLVM)
        body = _comment(previous, _record({"check-a": 101.0}))
        self.assertIn("No check changed by more than 10% and 10 s.", body)
        self.assertIn("(unchanged since 2026-10-07)", body)
        self.assertNotIn("[!NOTE]", body)

    def test_warns_about_a_different_runner(self):
        previous = _previous({"check-a": 1.0}, runner="x86-1")
        body = _comment(previous, _record({"check-a": 1.0}))
        self.assertIn("The previous run used runner `x86-1`", body)


def _bot_comment(body, number):
    return {
        "body": body,
        "html_url": f"https://github.com/org/repo/issues/7#issuecomment-{number}",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }


class FakeClient:
    def __init__(self, pages=(), issues=(), fail_label=None):
        self.pages = {index + 1: page for index, page in enumerate(pages)}
        self.issues = list(issues)
        self.fail_label = fail_label
        self.gets = []
        self.posts = []

    def get(self, path, params=None):
        self.gets.append((path, dict(params or {})))
        if path.endswith("/comments"):
            return self.pages.get(params["page"], [])
        return self.issues

    def post(self, path, payload):
        self.posts.append((path, payload))
        if path.endswith("/labels") and self.fail_label:
            raise GitHubError(f"POST {path} failed: {self.fail_label}")
        return {"number": 42}


class TestFetchLatestRecord(unittest.TestCase):
    def setUp(self):
        self.old = _comment(None, _record({"check-a": 1.0}, date="2026-10-06"))
        self.new = _comment(None, _record({"check-a": 2.0}, date="2026-10-07"))

    def test_starts_from_the_last_page(self):
        first = [_bot_comment(self.old, n) for n in range(100)]
        client = FakeClient(pages=[first, [_bot_comment(self.new, 100)]])
        record = fetch_latest_record(client, "org/repo", {"number": 7, "comments": 101})
        self.assertEqual(record.date, "2026-10-07")
        self.assertTrue(record.url.endswith("#issuecomment-100"))
        self.assertEqual([params["page"] for _, params in client.gets], [2])

    def test_skips_people_and_other_comments(self):
        person = dict(_bot_comment(self.new, 3), user={"login": "me", "type": "User"})
        page = [_bot_comment(self.old, 1), _bot_comment("Thanks!", 2), person]
        client = FakeClient(pages=[page])
        record = fetch_latest_record(client, "org/repo", {"number": 7, "comments": 3})
        self.assertEqual(record.date, "2026-10-06")

    def test_walks_back_to_earlier_pages(self):
        notes = [_bot_comment("note", n) for n in range(100)]
        client = FakeClient(pages=[[_bot_comment(self.old, 0)], notes])
        record = fetch_latest_record(client, "org/repo", {"number": 7, "comments": 101})
        self.assertEqual(record.date, "2026-10-06")

    def test_issue_without_comments(self):
        client = FakeClient()
        self.assertIsNone(
            fetch_latest_record(client, "org/repo", {"number": 7, "comments": 0})
        )


class TestTrackingIssue(unittest.TestCase):
    def test_skips_pull_requests(self):
        client = FakeClient(issues=[{"number": 1, "pull_request": {}}, {"number": 2}])
        self.assertEqual(find_tracking_issue(client, "org/repo")["number"], 2)

    def test_none_when_missing(self):
        self.assertIsNone(find_tracking_issue(FakeClient(), "org/repo"))

    def test_creates_label_and_issue(self):
        client = FakeClient()
        self.assertEqual(create_tracking_issue(client, "org/repo"), 42)
        self.assertEqual(
            [path for path, _ in client.posts],
            ["repos/org/repo/labels", "repos/org/repo/issues"],
        )
        self.assertEqual(client.posts[1][1]["labels"], ["check-timings"])

    def test_existing_label_is_fine(self):
        client = FakeClient(fail_label='422 {"code":"already_exists"}')
        self.assertEqual(create_tracking_issue(client, "org/repo"), 42)

    def test_other_label_errors_propagate(self):
        client = FakeClient(fail_label="403 Forbidden")
        with self.assertRaises(GitHubError):
            create_tracking_issue(client, "org/repo")


if __name__ == "__main__":
    unittest.main()
