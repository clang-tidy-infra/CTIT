import unittest

from crash_detection.detect_crashes import (
    MAX_CRASH_LINES,
    AnalyzerSite,
    analyzer_site,
    check_from_context,
    find_crashes_in_lines,
    group_by_check,
)

STACK_DUMP = [
    "PLEASE submit a bug report to https://github.com/llvm/llvm-project/issues/\n",
    "Stack dump:\n",
    "0.\tProgram arguments: clang-tidy foo.cpp\n",
    "1.\t<eof> parser at end of file\n",
    "2.\tASTMatcher: Processing 'bugprone-smart-ptr-initialization' against:\n",
    "\tVarDecl foo\n",
]

ANALYZER_DUMP = [
    "clang-tidy: /llvm/clang/lib/X.cpp:10: void f(): Assertion `x' failed.\n",
    "PLEASE submit a bug report to https://github.com/llvm/llvm-project/issues/\n",
    "Stack dump:\n",
    "0.\tProgram arguments: clang-tidy -checks=-*,clang-analyzer-x a.cpp\n",
    "1.\t<eof> parser at end of file\n",
    "2.\tWhile analyzing stack: \n",
    "\t#0 Calling inlined(int, float) at line 17\n",
    "\t#1 Calling test()\n",
    "3.\t/w/test_projects/proj/src/a.cpp:13:3: Error evaluating statement\n",
    " #0 0x000055d1 llvm::sys::PrintStackTrace(llvm::raw_ostream&, int)\n",
    " #1 0x000055d2 clang::ento::ExprEngine::Visit(clang::Stmt const*)\n",
]


class TestCheckFromContext(unittest.TestCase):
    def test_check_from_ast_matcher_line(self):
        self.assertEqual(
            check_from_context(STACK_DUMP), "bugprone-smart-ptr-initialization"
        )

    def test_matching_line_is_recognized(self):
        context = ["2.\tASTMatcher: Matching 'modernize-use-auto' against:\n"]
        self.assertEqual(check_from_context(context), "modernize-use-auto")

    def test_falls_back_to_stack_phase(self):
        context = ["Stack dump:\n", "1.\t<eof> parser at end of file\n"]
        self.assertEqual(
            check_from_context(context), "unknown (<eof> parser at end of file)"
        )

    def test_unknown_without_context(self):
        self.assertEqual(check_from_context(["Stack dump:\n"]), "unknown")

    def test_analyzer_crash_names_its_phase(self):
        self.assertEqual(
            check_from_context(ANALYZER_DUMP),
            "clang-analyzer (Error evaluating statement)",
        )

    def test_analyzer_crash_without_phase(self):
        context = [
            "Stack dump:\n",
            "1.\t<eof> parser at end of file\n",
            "2.\tWhile analyzing stack: \n",
            "\t#0 Calling test()\n",
        ]
        self.assertEqual(check_from_context(context), "clang-analyzer")

    def test_analyzer_backtrace_frame(self):
        context = [
            "Stack dump:\n",
            "1.\t<eof> parser at end of file\n",
            " #8 0x0001 clang::ento::PathSensitiveBugReport::addVisitor()\n",
        ]
        self.assertEqual(check_from_context(context), "clang-analyzer")


class TestAnalyzerSite(unittest.TestCase):
    def test_innermost_call_and_statement(self):
        self.assertEqual(
            analyzer_site(ANALYZER_DUMP),
            AnalyzerSite(
                function="inlined(int, float)",
                file_path="/w/test_projects/proj/src/a.cpp",
                line=13,
                phase="Error evaluating statement",
            ),
        )

    def test_statement_without_location(self):
        site = analyzer_site(["3.\tError evaluating branch\n"])
        self.assertEqual(site, AnalyzerSite(phase="Error evaluating branch"))

    def test_none_outside_the_analyzer(self):
        self.assertIsNone(analyzer_site(STACK_DUMP))
        self.assertIsNone(analyzer_site(["#0 Calling test()\n"]))


class TestFindCrashes(unittest.TestCase):
    def test_no_crash(self):
        lines = ["/path/file.cpp:1:1: warning: msg [check-a]\n", "    int x;\n"]
        self.assertEqual(find_crashes_in_lines(lines), [])

    def test_single_crash_keeps_context(self):
        crashes = find_crashes_in_lines(["[1/2] processing\n", *STACK_DUMP])
        self.assertEqual(len(crashes), 1)
        self.assertEqual(crashes[0].check, "bugprone-smart-ptr-initialization")
        self.assertIn("Stack dump:\n", crashes[0].lines)

    def test_related_lines_are_one_crash(self):
        # "PLEASE submit" and "Stack dump:" belong to the same crash.
        self.assertEqual(len(find_crashes_in_lines(STACK_DUMP)), 1)

    def test_context_is_capped(self):
        lines = ["Stack dump:\n"] + [f" #{i} frame\n" for i in range(100)]
        self.assertEqual(len(find_crashes_in_lines(lines)[0].lines), MAX_CRASH_LINES)

    def test_llvm_error_is_a_crash(self):
        crashes = find_crashes_in_lines(["LLVM ERROR: out of memory\n"])
        self.assertEqual(len(crashes), 1)

    def test_assertion_is_a_crash(self):
        crashes = find_crashes_in_lines(
            ['clang-tidy: Assertion `Node && "null"\' failed.\n']
        )
        self.assertEqual(len(crashes), 1)

    def test_multiple_crashes(self):
        lines = [*STACK_DUMP, *(["\n"] * MAX_CRASH_LINES), *STACK_DUMP]
        self.assertEqual(len(find_crashes_in_lines(lines)), 2)


class TestGroupByCheck(unittest.TestCase):
    def test_groups_by_check_name(self):
        lines = [*STACK_DUMP, *(["\n"] * MAX_CRASH_LINES), "LLVM ERROR: boom\n"]
        grouped = group_by_check(find_crashes_in_lines(lines))
        self.assertEqual(
            sorted(grouped), ["bugprone-smart-ptr-initialization", "unknown"]
        )
        self.assertEqual(len(grouped["bugprone-smart-ptr-initialization"]), 1)

    def test_empty(self):
        self.assertEqual(group_by_check([]), {})


if __name__ == "__main__":
    unittest.main()
