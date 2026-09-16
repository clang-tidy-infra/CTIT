import unittest

from pr_watcher.find_new_check_prs import CheckTarget
from pr_watcher.github_api import GitHubError
from pr_watcher.sync_issues import (
    CREATE,
    FAILED,
    REDO,
    SKIP,
    Action,
    IssueRef,
    IssueState,
    format_marker,
    format_summary,
    apply_actions,
    index_issues,
    parse_issue_ref,
    plan_actions,
    read_issue_state,
)

HEAD = "ea6429df66a95822a3ad5617479c53158b07b57f"
OLD_HEAD = "1111111111111111111111111111111111111111"


def _target(
    pr_number=181570,
    check_name="bugprone-smart-ptr-initialization",
    head_sha=HEAD,
):
    return CheckTarget(
        pr_number=pr_number,
        pr_url=f"https://github.com/llvm/llvm-project/pull/{pr_number}",
        pr_title=f"[clang-tidy] Add {check_name} check",
        updated_at="2026-09-13T12:00:00Z",
        head_sha=head_sha,
        check_name=check_name,
        language="cpp",
    )


def _issue(
    number=10,
    pr_number=181570,
    check="bugprone-smart-ptr-initialization",
    state="open",
    labels=("cpp",),
    body=None,
    created_at="2026-09-01T00:00:00Z",
):
    return IssueRef(
        number=number,
        pr_number=pr_number,
        check_name=check,
        state=state,
        labels=frozenset(labels),
        body=body if body is not None else "",
        created_at=created_at,
    )


def _probe(recently_triggered=False, tested_sha=None):
    return lambda _issue: IssueState(recently_triggered, tested_sha)


_never = _probe()


class TestParseIssueRef(unittest.TestCase):
    def test_reads_pull_request_and_check(self):
        payload = {
            "number": 209,
            "state": "open",
            "created_at": "2026-09-09T00:00:00Z",
            "labels": [{"name": "cpp"}],
            "body": "https://github.com/llvm/llvm-project/pull/222159 "
            "performance-inefficient-container-assignment\n",
        }
        issue = parse_issue_ref(payload)
        self.assertEqual(issue.pr_number, 222159)
        self.assertEqual(
            issue.check_name, "performance-inefficient-container-assignment"
        )
        self.assertEqual(issue.labels, frozenset({"cpp"}))

    def test_tolerates_unrelated_issue_body(self):
        issue = parse_issue_ref({"number": 214, "body": "Update cmake version"})
        self.assertIsNone(issue.pr_number)
        self.assertIsNone(issue.check_name)

    def test_tolerates_empty_body(self):
        issue = parse_issue_ref({"number": 1, "body": None})
        self.assertIsNone(issue.pr_number)


class TestIndexIssues(unittest.TestCase):
    def test_prefers_open_issue_over_newer_closed_one(self):
        closed = _issue(number=20, state="closed")
        opened = _issue(number=10, state="open")
        index = index_issues([closed, opened])
        self.assertEqual(
            index[(181570, "bugprone-smart-ptr-initialization")].number, 10
        )

    def test_prefers_newest_among_open_issues(self):
        index = index_issues([_issue(number=10), _issue(number=30)])
        self.assertEqual(
            index[(181570, "bugprone-smart-ptr-initialization")].number, 30
        )

    def test_skips_issues_without_a_tracked_check(self):
        self.assertEqual(index_issues([_issue(pr_number=None, check=None)]), {})


class TestPlanActions(unittest.TestCase):
    def test_creates_issue_when_none_tracks_the_check(self):
        actions = plan_actions([_target()], [], _never, limit=10)
        self.assertEqual([action.kind for action in actions], [CREATE])
        self.assertIsNone(actions[0].issue_number)

    def test_redoes_existing_labeled_issue(self):
        actions = plan_actions([_target()], [_issue()], _never, limit=10)
        self.assertEqual(actions[0].kind, REDO)
        self.assertEqual(actions[0].issue_number, 10)

    def test_redoes_when_the_head_revision_moved(self):
        actions = plan_actions([_target()], [_issue()], _probe(False, OLD_HEAD), 10)
        self.assertEqual(actions[0].kind, REDO)
        self.assertIn(HEAD[:12], actions[0].reason)

    def test_skips_when_the_head_revision_is_unchanged(self):
        actions = plan_actions([_target()], [_issue()], _probe(False, HEAD), 10)
        self.assertEqual(actions[0].kind, SKIP)
        self.assertIn("no new commits", actions[0].reason)

    def test_compares_revisions_case_insensitively(self):
        actions = plan_actions([_target()], [_issue()], _probe(False, HEAD.upper()), 10)
        self.assertEqual(actions[0].kind, SKIP)

    def test_accepts_an_abbreviated_recorded_revision(self):
        actions = plan_actions([_target()], [_issue()], _probe(False, HEAD[:8]), 10)
        self.assertEqual(actions[0].kind, SKIP)

    def test_unchanged_revision_does_not_consume_the_limit(self):
        targets = [_target(pr_number=1), _target(pr_number=2)]
        issues = [_issue(number=5, pr_number=1)]
        actions = plan_actions(targets, issues, _probe(False, HEAD), limit=1)
        self.assertEqual([action.kind for action in actions], [SKIP, CREATE])

    def test_leaves_unlabeled_issue_alone(self):
        actions = plan_actions([_target()], [_issue(labels=())], _never, limit=10)
        self.assertEqual(actions[0].kind, SKIP)
        self.assertEqual(actions[0].issue_number, 10)
        self.assertIn("no cpp/c label", actions[0].reason)

    def test_unlabeled_issue_does_not_consume_the_limit(self):
        targets = [_target(pr_number=1), _target(pr_number=2)]
        issues = [_issue(number=5, pr_number=1, labels=())]
        actions = plan_actions(targets, issues, _never, limit=1)
        self.assertEqual([action.kind for action in actions], [SKIP, CREATE])

    def test_skips_issue_already_triggered_in_this_window(self):
        actions = plan_actions([_target()], [_issue()], _probe(True), limit=10)
        self.assertEqual(actions[0].kind, SKIP)
        self.assertEqual(actions[0].issue_number, 10)

    def test_stops_triggering_at_the_limit(self):
        targets = [_target(pr_number=number) for number in (1, 2, 3)]
        actions = plan_actions(targets, [], _never, limit=2)
        self.assertEqual([action.kind for action in actions], [CREATE, CREATE, SKIP])
        self.assertIn("limit of 2", actions[2].reason)

    def test_skipped_targets_do_not_consume_the_limit(self):
        targets = [_target(pr_number=1), _target(pr_number=2)]
        issues = [_issue(number=5, pr_number=1)]
        actions = plan_actions(targets, issues, _probe(True), limit=1)
        self.assertEqual([action.kind for action in actions], [SKIP, CREATE])


class TestReadIssueState(unittest.TestCase):
    def test_reads_the_revision_from_the_newest_marker(self):
        comments = [
            {
                "created_at": "2026-09-02T00:00:00Z",
                "body": f"/redo\n{format_marker(OLD_HEAD)}",
            },
            {
                "created_at": "2026-09-05T00:00:00Z",
                "body": f"/redo\n{format_marker(HEAD)}",
            },
        ]
        state = read_issue_state(_issue(), comments, "2026-09-10T00:00:00Z")
        self.assertEqual(state.tested_sha, HEAD)
        self.assertFalse(state.recently_triggered)

    def test_flags_a_marker_inside_the_window(self):
        comments = [{"created_at": "2026-09-13T00:00:00Z", "body": format_marker(HEAD)}]
        state = read_issue_state(_issue(), comments, "2026-09-12T00:00:00Z")
        self.assertTrue(state.recently_triggered)

    def test_reads_the_revision_recorded_in_the_issue_body(self):
        issue = _issue(body=f"link check\n\n{format_marker(HEAD)}\n")
        self.assertEqual(
            read_issue_state(issue, [], "2026-09-10T00:00:00Z").tested_sha, HEAD
        )

    def test_keeps_the_last_known_revision_across_a_legacy_marker(self):
        comments = [
            {"created_at": "2026-09-02T00:00:00Z", "body": format_marker(HEAD)},
            {"created_at": "2026-09-05T00:00:00Z", "body": "<!-- ctit-nightly -->"},
        ]
        state = read_issue_state(_issue(), comments, "2026-09-10T00:00:00Z")
        self.assertEqual(state.tested_sha, HEAD)

    def test_reads_the_revision_a_check_tester_run_recorded(self):
        """A run a human started by hand reports its revision the same way."""
        comments = [
            {
                "created_at": "2026-09-05T00:00:00Z",
                "body": f"### Results\n\n<!-- ctit-run sha={HEAD} -->\n",
            }
        ]
        state = read_issue_state(_issue(), comments, "2026-09-10T00:00:00Z")
        self.assertEqual(state.tested_sha, HEAD)

    def test_treats_an_in_flight_run_as_recent_activity(self):
        comments = [
            {
                "created_at": "2026-09-13T00:30:00Z",
                "body": "Run started: ...\n\n<!-- ctit-run -->",
            }
        ]
        state = read_issue_state(_issue(), comments, "2026-09-12T00:00:00Z")
        self.assertTrue(state.recently_triggered)
        self.assertIsNone(state.tested_sha)

    def test_ignores_comments_written_by_people(self):
        comments = [{"created_at": "2026-09-13T00:00:00Z", "body": "/redo please"}]
        state = read_issue_state(_issue(), comments, "2026-09-12T00:00:00Z")
        self.assertFalse(state.recently_triggered)
        self.assertIsNone(state.tested_sha)


class FlakyClient:
    """Fails the posts at the given call indexes, succeeds on the rest."""

    def __init__(self, fail_indexes=()):
        self.paths = []
        self.fail_indexes = set(fail_indexes)

    def post(self, path, payload):
        index = len(self.paths)
        self.paths.append(path)
        if index in self.fail_indexes:
            raise GitHubError(f"boom on {path}")
        return {"number": 90 + index}


class TestApplyActions(unittest.TestCase):
    def test_one_failure_does_not_stop_the_rest(self):
        actions = [
            Action(CREATE, _target(pr_number=1), "new"),
            Action(CREATE, _target(pr_number=2), "new"),
        ]
        client = FlakyClient(fail_indexes={0})
        applied = apply_actions(client, "org/repo", actions)
        self.assertEqual([action.kind for action in applied], [FAILED, CREATE])
        self.assertIn("boom", applied[0].reason)
        self.assertEqual(applied[1].issue_number, 91)

    def test_a_failed_create_is_not_counted_as_triggered(self):
        applied = apply_actions(
            FlakyClient(fail_indexes={0}),
            "org/repo",
            [Action(CREATE, _target(), "new")],
        )
        summary = format_summary(applied, "2026-09-13T00:00:00Z")
        self.assertIn("**Triggered 0 of 1 candidate run(s).**", summary)

    def test_labels_the_issue_it_just_opened(self):
        client = FlakyClient()
        apply_actions(client, "org/repo", [Action(CREATE, _target(), "new")])
        self.assertEqual(
            client.paths, ["repos/org/repo/issues", "repos/org/repo/issues/90/labels"]
        )

    def test_redo_failure_is_recorded(self):
        applied = apply_actions(
            FlakyClient(fail_indexes={0}),
            "org/repo",
            [Action(REDO, _target(), "new commits", 10)],
        )
        self.assertEqual(applied[0].kind, FAILED)
        self.assertEqual(applied[0].issue_number, 10)


class TestFormatSummary(unittest.TestCase):
    def test_renders_one_row_per_action(self):
        actions = [Action(CREATE, _target(), "new", 42)]
        summary = format_summary(actions, "2026-09-13T00:00:00Z")
        self.assertIn(
            "| [#181570](https://github.com/llvm/llvm-project/pull/181570)", summary
        )
        self.assertIn("`bugprone-smart-ptr-initialization`", summary)
        self.assertIn("#42", summary)
        self.assertIn("**Triggered 1 of 1 candidate run(s).**", summary)

    def test_reports_an_empty_night(self):
        summary = format_summary([], "2026-09-13T00:00:00Z")
        self.assertIn("No llvm-project pull request added a new check", summary)


if __name__ == "__main__":
    unittest.main()
