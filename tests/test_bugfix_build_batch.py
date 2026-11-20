import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from bugfix_batch.build_batch import integrate
from bugfix_batch.plan import (
    BatchEntry,
    BuildResult,
    Plan,
    Skipped,
    git_apply,
    joined_checks,
    read_build_result,
    read_plan,
    write_build_result,
    write_plan,
)

TEST_FILE = "clang-tools-extra/test/case.cpp"
UNIT_TEST_FILE = "clang-tools-extra/unittests/Test.cpp"


def _entry(number, checks=None):
    return BatchEntry(
        pr_number=number,
        pr_url=f"https://github.com/llvm/llvm-project/pull/{number}",
        pr_title=f"Fix {number}",
        head_sha="a" * 40,
        checks=checks or (f"check-{number}",),
    )


class FakeTree:
    """An LLVM checkout that fails to build while a broken patch is applied."""

    def __init__(self, unappliable=(), broken=(), irreversible=(), unbuildable=False):
        self.unappliable = set(unappliable)
        self.broken = set(broken)
        self.irreversible = set(irreversible)
        self.unbuildable = unbuildable
        self.applied = []
        self.builds = []

    def apply(self, entry):
        if entry.pr_number in self.unappliable:
            return False
        self.applied.append(entry.pr_number)
        return True

    def revert(self, entry):
        if entry.pr_number in self.irreversible:
            return False
        self.applied.remove(entry.pr_number)
        return True

    def build(self):
        self.builds.append(list(self.applied))
        return not self.unbuildable and not self.broken & set(self.applied)

    def integrate(self, entries):
        return integrate(entries, self.apply, self.revert, self.build)


class TestIntegrate(unittest.TestCase):
    def test_builds_after_every_patch(self):
        tree = FakeTree()
        built, failed = tree.integrate((_entry(1), _entry(2)))
        self.assertEqual([entry.pr_number for entry in built], [1, 2])
        self.assertEqual(failed, [])
        self.assertEqual(tree.builds, [[1], [1, 2]])

    def test_broken_patch_costs_only_itself(self):
        tree = FakeTree(broken={2})
        built, failed = tree.integrate((_entry(1), _entry(2), _entry(3)))
        self.assertEqual([entry.pr_number for entry in built], [1, 3])
        self.assertEqual(failed, [Skipped.of(_entry(2), "does not compile")])
        self.assertEqual(tree.applied, [1, 3])

    def test_rebuilds_after_a_broken_last_patch(self):
        tree = FakeTree(broken={2})
        tree.integrate((_entry(1), _entry(2)))
        self.assertEqual(tree.builds[-1], [1])

    def test_unapplicable_patch_is_dropped_without_a_build(self):
        tree = FakeTree(unappliable={1})
        built, failed = tree.integrate((_entry(1), _entry(2)))
        self.assertEqual([entry.pr_number for entry in built], [2])
        self.assertEqual(failed, [Skipped.of(_entry(1), "patch does not apply")])
        self.assertEqual(tree.builds[0], [2])

    def test_every_patch_broken_leaves_a_clean_tree(self):
        tree = FakeTree(broken={1, 2})
        built, failed = tree.integrate((_entry(1), _entry(2)))
        self.assertEqual(built, [])
        self.assertEqual(len(failed), 2)
        self.assertEqual(tree.builds[-1], [])

    def test_stops_when_a_revert_fails(self):
        tree = FakeTree(broken={1}, irreversible={1})
        with self.assertRaisesRegex(RuntimeError, "could not revert PR 1"):
            tree.integrate((_entry(1), _entry(2)))

    def test_stops_when_the_surviving_patches_do_not_build(self):
        tree = FakeTree(unbuildable=True)
        with self.assertRaisesRegex(RuntimeError, "does not build"):
            tree.integrate((_entry(1),))


class TestGitApply(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = str(self.root / "llvm")
        self._git("init", "-q", self.repo, cwd=str(self.root))
        for path in ("Check.cpp", TEST_FILE, UNIT_TEST_FILE, "Notes.md"):
            full = self.root / "llvm" / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("old\n")
        self._git("add", ".")
        self._git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "base",
        )

    def _git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _patch(self, paths):
        for path in paths:
            (self.root / "llvm" / path).write_text("new\n")
        patch = self.root / "fix.diff"
        patch.write_text(self._git("diff"))
        self._git("checkout", ".")
        return patch

    def _read(self, path):
        return (self.root / "llvm" / path).read_text()

    def test_applies_only_what_reaches_the_binary(self):
        patch = self._patch(["Check.cpp", TEST_FILE, UNIT_TEST_FILE, "Notes.md"])
        self.assertTrue(git_apply(self.repo, patch))
        self.assertEqual(self._read("Check.cpp"), "new\n")
        self.assertEqual(self._read(TEST_FILE), "old\n")
        self.assertEqual(self._read(UNIT_TEST_FILE), "old\n")
        self.assertEqual(self._read("Notes.md"), "old\n")

    def test_excluded_conflicts_do_not_block_the_patch(self):
        patch = self._patch(["Check.cpp", "Notes.md"])
        (self.root / "llvm" / "Notes.md").write_text("drifted\n")
        self.assertTrue(git_apply(self.repo, patch, "--check"))

    def test_check_changes_nothing(self):
        patch = self._patch(["Check.cpp"])
        self.assertTrue(git_apply(self.repo, patch, "--check"))
        self.assertEqual(self._read("Check.cpp"), "old\n")

    def test_reverse_restores_the_tree(self):
        patch = self._patch(["Check.cpp", "Notes.md"])
        self.assertTrue(git_apply(self.repo, patch))
        self.assertTrue(git_apply(self.repo, patch, "--reverse"))
        self.assertEqual(self._git("status", "--porcelain"), "")

    def test_reports_a_conflict_and_leaves_the_tree_alone(self):
        patch = self._patch(["Check.cpp"])
        (self.root / "llvm" / "Check.cpp").write_text("drifted\n")
        self.assertFalse(git_apply(self.repo, patch))
        self.assertEqual(self._read("Check.cpp"), "drifted\n")


class TestPlanFiles(unittest.TestCase):
    def test_plan_round_trip(self):
        plan = Plan(
            entries=(_entry(1, ("check-a", "check-b")),),
            skipped=(Skipped(2, "url", "title", "reason"),),
        )
        with tempfile.TemporaryDirectory() as directory:
            write_plan(plan, os.path.join(directory, "batch"))
            self.assertEqual(read_plan(os.path.join(directory, "batch")), plan)

    def test_build_result_round_trip(self):
        result = BuildResult(
            llvm_revision="abc",
            built=(_entry(1),),
            failed=(Skipped.of(_entry(2), "does not compile"),),
        )
        with tempfile.TemporaryDirectory() as directory:
            write_build_result(result, directory)
            self.assertEqual(read_build_result(directory), result)

    def test_joined_checks(self):
        entries = (_entry(1, ("check-a", "check-b")), _entry(2, ("check-c",)))
        self.assertEqual(joined_checks(entries), "check-a,check-b,check-c")
        self.assertEqual(joined_checks(()), "")


if __name__ == "__main__":
    unittest.main()
