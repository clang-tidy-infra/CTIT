import tempfile
import unittest
from pathlib import Path

from bugfix_batch.plan import BatchEntry, BuildResult, Skipped
from bugfix_batch.publish_batch import (
    BatchRun,
    Outcome,
    crash_notice,
    create_issue,
    for_check,
    format_summary,
    load_results,
    post_report,
    publish,
    render_report,
)
from bugfix_batch.select_batch import checks_to_test
from crash_detection.detect_crashes import Crash
from pr_watcher.close_finished_issues import BUGFIX_LABEL, llvm_pr_number
from pr_watcher.github_api import GitHubError
from pr_watcher.sync_issues import (
    IssueRef,
    index_issues,
    parse_issue_ref,
    read_issue_state,
)
from slim_comment import GITHUB_COMMENT_LIMIT
from testers.generate_report import Issue, ProjectResult

HEAD = "ecd28fcb5ed9d29c3badb45f09c20008ba55aef7"
RUN_URL = "https://github.com/org/ctit/actions/runs/1"
ARTIFACT_URL = "https://github.com/org/ctit/actions/runs/1/artifacts/2"
REPO = "org/ctit"


def _entry(number=237924, checks=("check-a",)):
    return BatchEntry(
        pr_number=number,
        pr_url=f"https://github.com/llvm/llvm-project/pull/{number}",
        pr_title=f"Fix {number}",
        head_sha=HEAD,
        checks=checks,
    )


def _issue(line, check="check-a", severity="warning", message="bad code"):
    return Issue(
        file_path="src/a.cpp",
        line=line,
        col=1,
        severity=severity,
        message=message,
        check_name=check,
    )


def _project(issues=(), crashes=(), name="fmt", has_crash=None):
    return ProjectResult(
        name=name,
        warnings_count=sum(issue.severity == "warning" for issue in issues),
        errors_count=sum(issue.severity == "error" for issue in issues),
        has_crash=bool(crashes) if has_crash is None else has_crash,
        issues=list(issues),
        crashes=list(crashes),
        elapsed_seconds=12.5,
    )


def _run(built=None, failed=(), notice=""):
    built = (_entry(),) if built is None else built
    return BatchRun(
        build=BuildResult("abc123", built, failed),
        project_urls={"fmt": "https://github.com/fmtlib/fmt/blob/1"},
        run_url=RUN_URL,
        artifact_url=ARTIFACT_URL,
        crash_notice=notice,
    )


class FakeClient:
    """Records writes and hands out issue numbers."""

    def __init__(self, fail_on=()):
        self.fail_on = fail_on
        self.writes = []
        self.next_issue = 100

    def post(self, path, payload):
        if any(part in path or part in str(payload) for part in self.fail_on):
            raise GitHubError(f"boom on {path}")
        self.writes.append((path, payload))
        if path.endswith("/issues"):
            self.next_issue += 1
            return {"number": self.next_issue}
        return {}

    def paths(self):
        return [path for path, _payload in self.writes]


class TestLoadResults(unittest.TestCase):
    def test_reads_project_logs_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fmt.log").write_text(
                "/x/test_projects/fmt/src/a.cpp:3:1: warning: bad [check-a]\n"
            )
            (root / "progress.log").write_text("[1/1]\n")
            (root / "baseline").mkdir()
            (root / "baseline" / "fmt.log").write_text("")

            results = load_results(directory)

        self.assertEqual([result.name for result in results], ["fmt"])
        self.assertEqual(results[0].issues[0].file_path, "src/a.cpp")


class TestForCheck(unittest.TestCase):
    def test_keeps_only_this_check(self):
        project = _project(
            [
                _issue(1, "check-a"),
                _issue(2, "check-b"),
                _issue(3, "check-a", severity="error"),
            ]
        )
        narrowed = for_check(project, "check-a")
        self.assertEqual([issue.line for issue in narrowed.issues], [1, 3])
        self.assertEqual(narrowed.warnings_count, 1)
        self.assertEqual(narrowed.errors_count, 1)

    def test_compile_errors_belong_to_no_check(self):
        project = _project([_issue(1, "clang-diagnostic-error", severity="error")])
        self.assertEqual(for_check(project, "check-a").errors_count, 0)

    def test_name_must_match_exactly(self):
        project = _project([_issue(1, "check-a-more")])
        self.assertEqual(for_check(project, "check-a").issues, [])

    def test_diagnostic_of_a_check_registered_twice(self):
        project = _project([_issue(1, "check-a,check-b")])
        self.assertEqual(len(for_check(project, "check-b").issues), 1)

    def test_keeps_only_this_checks_crashes(self):
        mine = Crash(check="check-a", lines=["Stack dump:"])
        other = Crash(check="check-b", lines=["Stack dump:"])
        project = _project(crashes=[mine, other])

        self.assertEqual(for_check(project, "check-a").crashes, [mine])
        self.assertTrue(for_check(project, "check-a").has_crash)
        self.assertFalse(for_check(project, "check-c").has_crash)

    def test_drops_the_analysis_time_of_the_whole_batch(self):
        self.assertIsNone(for_check(_project(), "check-a").elapsed_seconds)


class TestCrashNotice(unittest.TestCase):
    def test_silent_without_crashes(self):
        self.assertEqual(crash_notice([_project()], [_project()]), "")

    def test_names_crashes_of_either_run(self):
        crash = Crash(check="check-b", lines=[])
        notice = crash_notice(
            [_project(crashes=[crash], name="fmt")],
            [_project(crashes=[crash], name="abseil"), _project(name="zlib")],
        )
        self.assertIn("`abseil`, `fmt`", notice)
        self.assertNotIn("zlib", notice)

    def test_includes_crashes_no_check_was_blamed_for(self):
        notice = crash_notice([_project(has_crash=True)], [])
        self.assertIn("`fmt`", notice)


class TestRenderReport(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "report.md"

    def _render(self, run=None, results=None, baseline=None, entry=None):
        return render_report(
            entry or _entry(),
            run or _run(),
            results if results is not None else [_project([_issue(1)])],
            baseline if baseline is not None else [_project([_issue(2)])],
            self.output,
        )

    def test_shows_the_change_against_the_baseline(self):
        report = self._render()
        self.assertIn("## Changes against baseline", report)
        self.assertIn("New in PR (1)", report)
        self.assertIn("Removed in PR (1)", report)
        self.assertIn("Baseline LLVM revision: `abc123`", report)

    def test_says_where_it_was_tested(self):
        report = self._render(run=_run(built=(_entry(1), _entry(2), _entry(3))))
        self.assertIn(f"Tested at `{HEAD[:12]}`", report)
        self.assertIn(RUN_URL, report)
        self.assertIn("with 3 pull request(s) applied", report)

    def test_keeps_the_crash_notice(self):
        self.assertIn("NOTICE", self._render(run=_run(notice="NOTICE\n\n")))

    def test_links_no_pull_request(self):
        # A link would add this comment to a pull request's timeline.
        run = _run(built=(_entry(1), _entry(2)))
        self.assertNotIn("llvm-project/pull", self._render(run=run, entry=_entry(1)))

    def test_fits_a_comment_and_keeps_the_marker(self):
        issues = [_issue(line, message="m" * 500) for line in range(1, 400)]
        report = self._render(results=[_project(issues)])
        self.assertLessEqual(len(report), GITHUB_COMMENT_LIMIT)
        self.assertTrue(report.startswith(f"<!-- ctit-nightly sha={HEAD} -->"))

    def test_leaves_the_posted_report_on_disk(self):
        report = self._render()
        self.assertEqual(self.output.read_text(), report)


class TestIssueRoundTrip(unittest.TestCase):
    """What this track writes must read back through pr_watcher."""

    def _issue_payload(self):
        client = FakeClient()
        number = create_issue(client, REPO, _entry(), "check-a")
        payload = {
            "number": number,
            "state": "open",
            "created_at": "2026-11-05T00:00:00Z",
            "labels": [{"name": name} for name in client.writes[1][1]["labels"]],
            "body": client.writes[0][1]["body"],
        }
        return payload

    def test_watcher_finds_the_issue(self):
        ref = parse_issue_ref(self._issue_payload())
        self.assertEqual((ref.pr_number, ref.check_name), (237924, "check-a"))
        self.assertEqual(ref.labels, {BUGFIX_LABEL})

    def test_close_finished_issues_finds_the_pull_request(self):
        self.assertEqual(llvm_pr_number(self._issue_payload()["body"]), 237924)

    def test_report_stops_the_next_batch_from_retesting(self):
        ref = parse_issue_ref(self._issue_payload())
        with tempfile.TemporaryDirectory() as directory:
            report = render_report(
                _entry(), _run(), [_project()], [_project()], Path(directory) / "r.md"
            )

        comments = [{"created_at": "2026-11-05T01:00:00Z", "body": report}]

        def probe(issue):
            return read_issue_state(issue, comments, "2026-11-05T00:00:00Z")

        index = index_issues([ref])
        self.assertEqual(checks_to_test(237924, HEAD, {"check-a"}, index, probe), ())
        self.assertEqual(
            checks_to_test(237924, "b" * 40, {"check-a"}, index, probe), ("check-a",)
        )


def _ref(number=7, check="check-a"):
    return IssueRef(
        number=number,
        pr_number=237924,
        check_name=check,
        state="open",
        labels=frozenset({BUGFIX_LABEL}),
        body="",
        created_at="2026-11-01T00:00:00Z",
    )


class TestPostReport(unittest.TestCase):
    def test_comments_on_the_existing_issue(self):
        client = FakeClient()
        number = post_report(client, REPO, _entry(), "check-a", _ref(), "report")
        self.assertEqual(number, 7)
        self.assertEqual(
            client.writes, [(f"repos/{REPO}/issues/7/comments", {"body": "report"})]
        )

    def test_opens_an_issue_with_no_trigger_label(self):
        client = FakeClient()
        number = post_report(client, REPO, _entry(), "check-a", None, "report")
        self.assertEqual(number, 101)
        self.assertEqual(
            client.paths(),
            [
                f"repos/{REPO}/issues",
                f"repos/{REPO}/issues/101/labels",
                f"repos/{REPO}/issues/101/comments",
            ],
        )
        self.assertEqual(client.writes[0][1]["title"], "[Bugfix] check-a")
        self.assertEqual(client.writes[1][1], {"labels": [BUGFIX_LABEL]})


class TestPublish(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.reports = Path(directory.name) / "reports"

    def _publish(self, client, run, results=None, baseline=None, dry_run=False):
        return publish(
            client,
            REPO,
            run,
            results if results is not None else [_project()],
            baseline if baseline is not None else [_project()],
            {},
            self.reports,
            dry_run,
        )

    def test_one_issue_per_check_of_the_batch(self):
        client = FakeClient()
        entries = (_entry(1, ("check-a", "check-b")), _entry(2, ("check-c",)))
        outcomes = self._publish(client, _run(built=entries))
        self.assertEqual(
            [(outcome.entry.pr_number, outcome.check) for outcome in outcomes],
            [(1, "check-a"), (1, "check-b"), (2, "check-c")],
        )
        self.assertEqual(client.paths().count(f"repos/{REPO}/issues"), 3)

    def test_each_issue_shows_only_its_own_check(self):
        client = FakeClient()
        entries = (_entry(1, ("check-a",)), _entry(2, ("check-b",)))
        results = [_project([_issue(1, "check-a"), _issue(2, "check-b")])]
        self._publish(client, _run(built=entries), results, [_project()])

        comments = [
            payload["body"]
            for path, payload in client.writes
            if path.endswith("/comments")
        ]
        self.assertIn("[check-a]", comments[0])
        self.assertNotIn("[check-b]", comments[0])
        self.assertIn("[check-b]", comments[1])
        self.assertNotIn("[check-a]", comments[1])

    def test_counts_the_change_per_check(self):
        results = [_project([_issue(1), _issue(2), _issue(9, "check-b")])]
        baseline = [_project([_issue(2), _issue(3)])]
        outcome = self._publish(FakeClient(), _run(), results, baseline)[0]
        self.assertEqual((outcome.new, outcome.removed), (1, 1))

    def test_a_failed_post_does_not_stop_the_rest(self):
        client = FakeClient(fail_on=("[Bugfix] check-a",))
        entries = (_entry(1, ("check-a",)), _entry(2, ("check-b",)))
        outcomes = self._publish(client, _run(built=entries))
        self.assertIn("boom", outcomes[0].error)
        self.assertIsNone(outcomes[1].error)
        self.assertEqual(outcomes[1].issue_number, 101)

    def test_a_failed_comment_leaves_no_marker_behind(self):
        client = FakeClient(fail_on=("/comments",))
        outcomes = self._publish(client, _run())
        self.assertIn("boom", outcomes[0].error)
        self.assertNotIn("ctit-nightly", str(client.writes))

    def test_dry_run_writes_reports_and_posts_nothing(self):
        client = FakeClient()
        outcomes = self._publish(client, _run(), dry_run=True)
        self.assertEqual(client.writes, [])
        self.assertIsNone(outcomes[0].error)
        self.assertTrue((self.reports / "237924-check-a.md").is_file())

    def test_nothing_built_posts_nothing(self):
        client = FakeClient()
        self.assertEqual(self._publish(client, _run(built=())), [])
        self.assertEqual(client.writes, [])


class TestFormatSummary(unittest.TestCase):
    def test_lists_results_failures_and_dropped_patches(self):
        build = BuildResult(
            "abc123",
            (_entry(),),
            (Skipped.of(_entry(2), "does not compile"),),
        )
        outcomes = [
            Outcome(_entry(), "check-a", 2, 3, issue_number=7),
            Outcome(_entry(), "check-b", 0, 0, error="boom | here"),
        ]
        summary = format_summary(outcomes, build, dry_run=False)
        self.assertIn("| `check-a` | 2 | 3 | #7 |", summary)
        self.assertIn("failed: boom \\| here", summary)
        self.assertIn("does not compile", summary)
        self.assertNotIn("dry run", summary)

    def test_marks_a_dry_run(self):
        summary = format_summary([], BuildResult("abc", (), ()), dry_run=True)
        self.assertIn("(dry run)", summary)


if __name__ == "__main__":
    unittest.main()
