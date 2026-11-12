import unittest

from bugfix_batch.plan import BatchEntry, Plan, Skipped
from bugfix_batch.select_batch import (
    Candidate,
    Ineligible,
    changed_checks,
    checks_to_test,
    ci_problem,
    collect_candidates,
    evaluate,
    format_summary,
    is_excluded,
    pick_batch,
)
from pr_watcher.github_api import GitHubError
from pr_watcher.sync_issues import IssueRef, IssueState

TIDY = "clang-tools-extra/clang-tidy"
HEAD = "ecd28fcb5ed9d29c3badb45f09c20008ba55aef7"
OLD_HEAD = "1111111111111111111111111111111111111111"

OWNERS = {
    f"{TIDY}/misc/IncludeCleanerCheck.cpp": {"misc-include-cleaner"},
    f"{TIDY}/bugprone/ArgumentCommentCheck.cpp": {"bugprone-argument-comment"},
    f"{TIDY}/bugprone/ArgumentCommentCheck.h": {"bugprone-argument-comment"},
}


def _resolve(path):
    return OWNERS.get(path, set())


def _file(filename, status="modified"):
    return {"filename": filename, "status": status}


def _run(name, conclusion="success", status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion}


# What llvm/llvm-project#237775 reports while its CI waits for approval: only
# bots ran, and all of them are green.
AWAITING_APPROVAL = [
    _run("Graphite / mergeability_check"),
    _run("greeter", "skipped"),
    _run("automate-prs-labels"),
]
PASSED = [
    *AWAITING_APPROVAL,
    _run("Compute Projects"),
    _run("Build and Test Linux"),
    _run("Build and Test Windows"),
    _run("Build and Test macOS arm64"),
]


class TestIsExcluded(unittest.TestCase):
    def test_paths_that_never_reach_the_binary(self):
        for path in (
            "clang-tools-extra/docs/ReleaseNotes.md",
            "clang-tools-extra/docs/clang-tidy/checks/list.rst",
            "clang-tools-extra/test/clang-tidy/checkers/misc/foo.cpp",
            "clang-tools-extra/unittests/clang-tidy/IncludeCleanerTest.cpp",
        ):
            self.assertTrue(is_excluded(path), path)

    def test_check_source_is_kept(self):
        self.assertFalse(is_excluded(f"{TIDY}/misc/IncludeCleanerCheck.cpp"))


class TestChangedChecks(unittest.TestCase):
    def test_ignores_docs_and_tests_around_a_check_fix(self):
        # The files of llvm/llvm-project#237924.
        files = [
            _file(f"{TIDY}/misc/IncludeCleanerCheck.cpp"),
            _file("clang-tools-extra/docs/ReleaseNotes.md"),
            _file("clang-tools-extra/unittests/clang-tidy/IncludeCleanerTest.cpp"),
        ]
        self.assertEqual(changed_checks(files, _resolve), {"misc-include-cleaner"})

    def test_header_and_source_are_one_check(self):
        files = [
            _file(f"{TIDY}/bugprone/ArgumentCommentCheck.cpp"),
            _file(f"{TIDY}/bugprone/ArgumentCommentCheck.h"),
        ]
        self.assertEqual(changed_checks(files, _resolve), {"bugprone-argument-comment"})

    def test_collects_every_check_of_a_pull_request(self):
        files = [
            _file(f"{TIDY}/misc/IncludeCleanerCheck.cpp"),
            _file(f"{TIDY}/bugprone/ArgumentCommentCheck.cpp"),
        ]
        self.assertEqual(
            changed_checks(files, _resolve),
            {"misc-include-cleaner", "bugprone-argument-comment"},
        )

    def test_rejects_wider_changes(self):
        for path in (
            f"{TIDY}/utils/ExceptionAnalyzer.cpp",
            f"{TIDY}/ClangTidy.cpp",
            f"{TIDY}/cert/CERTTidyModule.cpp",
            f"{TIDY}/misc/CMakeLists.txt",
            "clang/lib/AST/ParentMapContext.cpp",
        ):
            files = [_file(f"{TIDY}/misc/IncludeCleanerCheck.cpp"), _file(path)]
            with self.assertRaisesRegex(Ineligible, path):
                changed_checks(files, _resolve)

    def test_rejects_a_check_source_that_is_not_just_modified(self):
        path = f"{TIDY}/misc/IncludeCleanerCheck.cpp"
        for status in ("removed", "renamed"):
            with self.assertRaises(Ineligible):
                changed_checks([_file(path, status)], _resolve)

    def test_leaves_new_checks_to_their_own_track(self):
        files = [
            _file(f"{TIDY}/bugprone/FooCheck.cpp", "added"),
            {
                "filename": f"{TIDY}/bugprone/BugproneTidyModule.cpp",
                "status": "modified",
                "patch": '@@ -1 +1,2 @@\n+CheckFactories.registerCheck<FooCheck>("bugprone-foo");\n',
            },
        ]
        with self.assertRaisesRegex(Ineligible, "new check"):
            changed_checks(files, _resolve)

    def test_rejects_pull_requests_without_check_sources(self):
        files = [_file("clang-tools-extra/docs/clang-tidy/checks/misc/foo.md")]
        with self.assertRaisesRegex(Ineligible, "no check source"):
            changed_checks(files, _resolve)


class TestCiProblem(unittest.TestCase):
    def test_passed(self):
        self.assertIsNone(ci_problem(PASSED))

    def test_green_bots_do_not_count_as_a_passed_ci(self):
        self.assertIn("has not run", ci_problem(AWAITING_APPROVAL))

    def test_no_check_runs_at_all(self):
        self.assertIn("has not run", ci_problem([]))

    def test_failed_suite(self):
        runs = [_run("Build and Test Linux"), _run("Build and Test Windows", "failure")]
        self.assertIn("failed: Build and Test Windows", ci_problem(runs))

    def test_cancelled_suite_is_not_a_pass(self):
        runs = [_run("Build and Test Linux", "cancelled")]
        self.assertIn("failed", ci_problem(runs))

    def test_running_suite(self):
        runs = [_run("Build and Test Linux", None, "in_progress")]
        self.assertIn("still running", ci_problem(runs))

    def test_skipped_linux_suite_is_not_a_pass(self):
        self.assertIn(
            "has not run", ci_problem([_run("Build and Test Linux", "skipped")])
        )

    def test_skipped_secondary_suite_is_fine(self):
        runs = [_run("Build and Test Linux"), _run("Build and Test Windows", "skipped")]
        self.assertIsNone(ci_problem(runs))

    def test_failures_outside_the_test_suites_do_not_matter(self):
        runs = [_run("Build and Test Linux"), _run("code_formatter", "failure")]
        self.assertIsNone(ci_problem(runs))


def _issue(labels=("test-bugfix",), number=10):
    return IssueRef(
        number=number,
        pr_number=1,
        check_name="check-a",
        state="open",
        labels=frozenset(labels),
        body="",
        created_at="2026-11-01T00:00:00Z",
    )


class TestChecksToTest(unittest.TestCase):
    def _todo(self, index, tested_sha=None, checks=("check-a",)):
        def probe(_issue):
            return IssueState(False, tested_sha)

        return checks_to_test(1, HEAD, set(checks), index, probe)

    def test_check_without_an_issue(self):
        self.assertEqual(self._todo({}), ("check-a",))

    def test_issue_never_tested(self):
        self.assertEqual(self._todo({(1, "check-a"): _issue()}), ("check-a",))

    def test_same_revision_is_not_tested_twice(self):
        index = {(1, "check-a"): _issue()}
        self.assertEqual(self._todo(index, HEAD), ())
        self.assertEqual(self._todo(index, HEAD[:12]), ())

    def test_new_revision_is_tested(self):
        index = {(1, "check-a"): _issue()}
        self.assertEqual(self._todo(index, OLD_HEAD), ("check-a",))

    def test_issue_of_the_other_track_is_left_alone(self):
        self.assertEqual(self._todo({(1, "check-a"): _issue(("test-cpp",))}), ())

    def test_muted_issue_is_left_alone(self):
        self.assertEqual(self._todo({(1, "check-a"): _issue(())}), ())

    def test_only_the_untested_checks_of_a_pull_request(self):
        index = {(1, "check-a"): _issue()}
        todo = self._todo(index, HEAD, checks=("check-a", "check-b"))
        self.assertEqual(todo, ("check-b",))


def _candidate(number, checks=None, files=None):
    checks = checks if checks is not None else {f"check-{number}"}
    return Candidate(
        entry=BatchEntry(
            pr_number=number,
            pr_url=f"https://github.com/llvm/llvm-project/pull/{number}",
            pr_title=f"Fix {number}",
            head_sha=HEAD,
            checks=tuple(sorted(checks)),
        ),
        changed_checks=frozenset(checks),
        files=frozenset(files if files is not None else {f"file-{number}.cpp"}),
    )


def _numbers(entries):
    return [entry.pr_number for entry in entries]


def _ignore(_entry):
    return None


class TestPickBatch(unittest.TestCase):
    def test_takes_distinct_candidates_in_order(self):
        entries, skipped = pick_batch([_candidate(1), _candidate(2)], _ignore, 10)
        self.assertEqual(_numbers(entries), [1, 2])
        self.assertEqual(skipped, [])

    def test_one_pull_request_per_check(self):
        entries, skipped = pick_batch(
            [_candidate(1, {"check-a"}), _candidate(2, {"check-a"})], _ignore, 10
        )
        self.assertEqual(_numbers(entries), [1])
        self.assertEqual(skipped[0].pr_number, 2)
        self.assertIn("overlaps PR 1", skipped[0].reason)

    def test_shared_file_conflicts_even_with_distinct_checks(self):
        entries, skipped = pick_batch(
            [_candidate(1, files={"a.cpp"}), _candidate(2, files={"a.cpp"})],
            _ignore,
            10,
        )
        self.assertEqual(_numbers(entries), [1])
        self.assertIn("overlaps PR 1", skipped[0].reason)

    def test_conflict_counts_a_check_that_was_already_tested(self):
        # PR 1 only reports on check-b but its patch still changes check-a.
        first = Candidate(
            entry=BatchEntry(1, "url", "title", HEAD, ("check-b",)),
            changed_checks=frozenset({"check-a", "check-b"}),
            files=frozenset({"a.cpp", "b.cpp"}),
        )
        entries, _skipped = pick_batch([first, _candidate(2, {"check-a"})], _ignore, 10)
        self.assertEqual(_numbers(entries), [1])

    def test_limit(self):
        entries, skipped = pick_batch([_candidate(n) for n in (1, 2, 3)], _ignore, 2)
        self.assertEqual(_numbers(entries), [1, 2])
        self.assertIn("limit of 2", skipped[0].reason)

    def test_unusable_patch_frees_its_place_and_its_check(self):
        def prepare(entry):
            if entry.pr_number == 1:
                raise Ineligible("patch does not apply to the pinned LLVM")

        entries, skipped = pick_batch(
            [
                _candidate(1, {"check-a"}),
                _candidate(2, {"check-a"}),
                _candidate(3),
            ],
            prepare,
            2,
        )
        self.assertEqual(_numbers(entries), [2, 3])
        self.assertEqual(skipped[0].pr_number, 1)
        self.assertIn("does not apply", skipped[0].reason)

    def test_does_not_prepare_what_it_would_not_take(self):
        prepared = []
        pick_batch(
            [_candidate(1, {"check-a"}), _candidate(2, {"check-a"}), _candidate(3)],
            lambda entry: prepared.append(entry.pr_number),
            1,
        )
        self.assertEqual(prepared, [1])


class FakeClient:
    """Serves one pull request's files, details and check runs."""

    def __init__(self, base="main", check_runs=None, fail=()):
        self.base = base
        self.check_runs = PASSED if check_runs is None else check_runs
        self.fail = set(fail)
        self.requests = []

    def _serve(self, path):
        self.requests.append(path)
        number = path.split("/")[4] if "/pulls/" in path else None
        if number in self.fail:
            raise GitHubError(f"boom on {path}")

    def paginate(self, path, params=None, items_key=None):
        self._serve(path)
        if path.endswith("/files"):
            return [_file(f"{TIDY}/misc/IncludeCleanerCheck.cpp")]
        return self.check_runs

    def get(self, path, params=None):
        self._serve(path)
        return {"base": {"ref": self.base}, "head": {"sha": HEAD}}


def _pull(number=237924):
    return {"number": number, "title": f"Fix {number}"}


def _never_tested(_issue):
    return IssueState(False, None)


class TestEvaluate(unittest.TestCase):
    REPO = "llvm/llvm-project"

    def _evaluate(self, client, index=None):
        return evaluate(
            client, self.REPO, _pull(), _resolve, index or {}, _never_tested
        )

    def test_builds_a_candidate(self):
        candidate = self._evaluate(FakeClient())
        self.assertEqual(
            candidate.entry,
            BatchEntry(
                pr_number=237924,
                pr_url="https://github.com/llvm/llvm-project/pull/237924",
                pr_title="Fix 237924",
                head_sha=HEAD,
                checks=("misc-include-cleaner",),
            ),
        )
        self.assertEqual(
            candidate.files, frozenset({f"{TIDY}/misc/IncludeCleanerCheck.cpp"})
        )

    def test_rejects_backports(self):
        with self.assertRaisesRegex(Ineligible, "targets release/23.x"):
            self._evaluate(FakeClient(base="release/23.x"))

    def test_rejects_ci_that_never_ran(self):
        with self.assertRaisesRegex(Ineligible, "has not run"):
            self._evaluate(FakeClient(check_runs=AWAITING_APPROVAL))

    def test_asks_for_ci_only_when_something_is_left_to_test(self):
        client = FakeClient()
        index = {(237924, "misc-include-cleaner"): _issue(("test-cpp",))}
        with self.assertRaisesRegex(Ineligible, "no check left"):
            self._evaluate(client, index)
        self.assertFalse(any("check-runs" in path for path in client.requests))


class TestCollectCandidates(unittest.TestCase):
    def test_a_failing_pull_request_costs_only_itself(self):
        client = FakeClient(fail={"1"})
        candidates, skipped = collect_candidates(
            client,
            "llvm/llvm-project",
            [_pull(1), _pull(2)],
            _resolve,
            {},
            _never_tested,
        )
        self.assertEqual([c.entry.pr_number for c in candidates], [2])
        self.assertEqual(skipped[0].pr_number, 1)
        self.assertIn("boom", skipped[0].reason)


class TestFormatSummary(unittest.TestCase):
    def test_lists_entries_and_reasons(self):
        plan = Plan(
            entries=(BatchEntry(1, "url1", "Fix a", HEAD, ("check-a", "check-b")),),
            skipped=(Skipped(2, "url2", "Fix | b", "LLVM CI failed: x|y"),),
        )
        summary = format_summary(plan, "2026-11-01T00:00:00Z")
        self.assertIn("**batched:** `check-a`, `check-b`", summary)
        self.assertIn("Fix \\| b", summary)
        self.assertIn("LLVM CI failed: x\\|y", summary)
        self.assertIn("Batched 1 pull request(s)", summary)

    def test_quiet_window(self):
        summary = format_summary(Plan((), ()), "2026-11-01T00:00:00Z")
        self.assertIn("No clang-tidy pull request", summary)


if __name__ == "__main__":
    unittest.main()
