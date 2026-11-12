import unittest

from pr_watcher.analyzer_checkers import (
    CHECKERS_TD,
    new_analyzer_checkers,
    skip_reason,
)

DOCS_MD = "clang/docs/analyzer/checkers.md"
DOCS_RST = "clang/docs/analyzer/checkers.rst"

FSETPOS_TD_PATCH = """@@ -560,6 +560,10 @@ def StreamChecker : Checker<"Stream">,
   Documentation<HasDocumentation>;

+def FsetposChecker : Checker<"fsetpos">,
+  HelpText<"Check that fsetpos gets a position from fgetpos">,
+  Documentation<HasDocumentation>;
+
 def SimpleStreamChecker : Checker<"SimpleStream">,"""

FSETPOS_DOCS_PATCH = """@@ -2100,6 +2100,14 @@ The analyzer models stream functions.

+(unix-fsetpos)=
+
+#### unix.fsetpos (C)
+
+Check that the position passed to `fsetpos` comes from `fgetpos`.
+
 #### unix.Stream (C)"""


def pull_files(td_patch, docs_patch, docs=DOCS_MD):
    return [
        {"filename": CHECKERS_TD, "status": "modified", "patch": td_patch},
        {"filename": docs, "status": "modified", "patch": docs_patch},
    ]


class TestNewAnalyzerCheckers(unittest.TestCase):
    def test_reports_checker_with_new_def_and_heading(self):
        """Mirrors llvm/llvm-project#234672."""
        files = pull_files(FSETPOS_TD_PATCH, FSETPOS_DOCS_PATCH)
        self.assertEqual(new_analyzer_checkers(files), {"unix.fsetpos": "c"})

    def test_reads_rst_headings(self):
        """llvm/llvm-project#221184 still documents its checker in checkers.rst."""
        td_patch = (
            "@@ -1 +1,2 @@\n"
            '+def UnsafeSymlinkTestChecker : Checker<"UnsafeSymlinkTest">,\n'
        )
        docs_patch = (
            "@@ -1 +1,4 @@\n"
            "+.. _security-UnsafeSymlinkTest:\n"
            "+\n"
            "+security.UnsafeSymlinkTest (C, C++)\n"
            '+""""""""""""""""""""""""""""""""""""\n'
        )
        self.assertEqual(
            new_analyzer_checkers(pull_files(td_patch, docs_patch, DOCS_RST)),
            {"security.UnsafeSymlinkTest": "cpp"},
        )

    def test_reports_heading_without_languages(self):
        td_patch = '@@ -1 +1 @@\n+def FooChecker : Checker<"Foo">,\n'
        docs_patch = "@@ -1 +1 @@\n+#### optin.portability.Foo\n"
        self.assertEqual(
            new_analyzer_checkers(pull_files(td_patch, docs_patch)),
            {"optin.portability.Foo": "cpp"},
        )

    def test_reports_checker_moved_out_of_alpha_with_its_def(self):
        """Mirrors llvm/llvm-project#89247, which moved alpha.unix.Stream."""
        td_patch = (
            "@@ -1,3 +1,3 @@\n"
            '-def StreamChecker : Checker<"Stream">,\n'
            '+def StreamChecker : Checker<"Stream">,\n'
        )
        docs_patch = "@@ -1 +1 @@\n-#### alpha.unix.Stream (C)\n+#### unix.Stream (C)\n"
        self.assertEqual(
            new_analyzer_checkers(pull_files(td_patch, docs_patch)),
            {"unix.Stream": "c"},
        )

    def test_reports_promotion_that_moves_only_the_package_block(self):
        """llvm/llvm-project#117791 left the ChrootChecker def in place."""
        td_patch = (
            "@@ -599,6 +599,6 @@\n"
            "-let ParentPackage = UnixAlpha in {\n"
            ' def ChrootChecker : Checker<"Chroot">,\n'
            "+let ParentPackage = UnixAlpha in {\n"
        )
        docs_patch = "@@ -1 +1 @@\n-alpha.unix.Chroot (C)\n+unix.Chroot (C)\n"
        self.assertEqual(
            new_analyzer_checkers(pull_files(td_patch, docs_patch, DOCS_RST)),
            {"unix.Chroot": "c"},
        )

    def test_ignores_documentation_for_an_existing_checker(self):
        """llvm/llvm-project#218272 documented alpha.core.UseAfterLifetimeEnd."""
        td_patch = (
            "@@ -300,3 +300,3 @@\n"
            ' def UseAfterLifetimeEnd : Checker<"UseAfterLifetimeEnd">,\n'
            "-  Documentation<NotDocumented>;\n"
            "+  Documentation<HasDocumentation>;\n"
        )
        docs_patch = "@@ -1 +1 @@\n+#### alpha.core.UseAfterLifetimeEnd (C++)\n"
        self.assertEqual(new_analyzer_checkers(pull_files(td_patch, docs_patch)), {})

    def test_ignores_defs_that_the_diff_only_realigned(self):
        """llvm/llvm-project#157129 re-added the NonNullParamChecker def line."""
        td_patch = (
            "@@ -1,2 +1,6 @@\n"
            '-def NonNullParamChecker : Checker<"NonNullParamChecker">,\n'
            '+def NullPointerArithmChecker : Checker<"NullPointerArithm">,\n'
            "+  Documentation<HasDocumentation>;\n"
            "+\n"
            '+def NonNullParamChecker : Checker<"NonNullParamChecker">,\n'
        )
        docs_patch = "@@ -1 +1 @@\n+#### core.NullPointerArithm (C, C++)\n"
        self.assertEqual(
            new_analyzer_checkers(pull_files(td_patch, docs_patch)),
            {"core.NullPointerArithm": "cpp"},
        )

    def test_ignores_section_headings(self):
        td_patch = '@@ -1 +1 @@\n+def UnixChecker : Checker<"unix">,\n'
        docs_patch = "@@ -1 +1,2 @@\n+### unix\n+#### unix generic options\n"
        self.assertEqual(new_analyzer_checkers(pull_files(td_patch, docs_patch)), {})

    def test_misses_checker_without_documentation(self):
        """llvm/llvm-project#205521 added its docs in a later pull request."""
        files = [{"filename": CHECKERS_TD, "patch": FSETPOS_TD_PATCH}]
        self.assertEqual(new_analyzer_checkers(files), {})


class TestSkipReason(unittest.TestCase):
    def test_skips_packages_absent_from_the_corpus(self):
        self.assertIn("webkit", skip_reason("alpha.webkit.NoDeleteChecker") or "")
        self.assertIn("osx", skip_reason("osx.cocoa.Loops") or "")

    def test_runs_other_checkers(self):
        self.assertIsNone(skip_reason("unix.fsetpos"))


if __name__ == "__main__":
    unittest.main()
