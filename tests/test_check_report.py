import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from testers.check_report import check_report


class TestCheckReport(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.logs = os.path.join(self.dir, "logs")
        self.projects = os.path.join(self.dir, "test_projects")
        os.makedirs(self.logs)
        os.makedirs(os.path.join(self.projects, "demo"))
        with open(os.path.join(self.projects, "demo", "a.cpp"), "w") as source:
            source.write(
                "void f();\n"
                # A statement split over two lines: the container is on the second.
                "for (Iter I = Pending.begin(),\n"
                "     E = Pending.end(); I != E; ++I)\n"
                "for (int i = 0; i < 4; ++i) // see Pending\n"
                "  Table[i] = 0;\n"
            )
        with open(os.path.join(self.logs, "demo.log"), "w") as log:
            log.write(
                "/w/test_projects/demo/a.cpp:2:1: warning: use range-based for [check-a]\n"
                "/w/test_projects/demo/a.cpp:4:1: warning: use range-based for [check-a]\n"
                # A file outside the clone: names come from clang-tidy's copy.
                "/w/test_projects/demo/gone.cpp:7:1: warning: use range-based for [check-a]\n"
                "    7 | for (auto It = Worklist.begin(); It != Worklist.end(); ++It)\n"
            )

    def check(self, *rows: tuple[str, str]) -> tuple[bool, str]:
        report = os.path.join(self.dir, "report.md")
        with open(report, "w") as stream:
            stream.write("| # | Project | Verdict | Rationale | Location |\n")
            stream.writelines(
                f"| {number} | demo | {verdict} | {rationale} | x |\n"
                for number, (verdict, rationale) in enumerate(rows, 1)
            )
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                check_report(self.logs, report, self.projects)
        except SystemExit:
            return False, output.getvalue()
        return True, output.getvalue()

    def test_rows_must_cite_their_own_source(self):
        passed, output = self.check(
            # Names only the generic begin/end of the split statement.
            ("TP", "Iterator loop from begin() to end()."),
            # Nothing specific to cite: any rationale passes.
            ("TP", "Same as #1"),
            ("FP", "Same as #1"),
        )
        self.assertFalse(passed)
        self.assertIn("#1 (demo a.cpp:2)", output)
        self.assertIn("Pending", output)
        self.assertNotIn("#2 ", output)
        self.assertIn("#3 (demo gone.cpp:7)", output)
        self.assertIn("Worklist", output)

    def test_passes_rationales_that_cite_the_code(self):
        passed, output = self.check(
            ("TP", "`Pending` is only read through I."),
            # Cites the body, which a fixed-size loop header has nothing to name.
            ("Uncertain", "Fixed-size loop over Table."),
            ("FP", "Same as #1: Worklist grows in the body."),
        )
        self.assertTrue(passed, output)

    def test_verdict_and_rationale_are_required(self):
        passed, output = self.check(
            ("TBD", "Pending"),
            ("TP", "TBD"),
            ("Maybe", "Worklist"),
        )
        self.assertFalse(passed)
        self.assertIn("#1 (demo a.cpp:2): verdict is 'TBD'", output)
        self.assertIn("#2 (demo a.cpp:4): no rationale", output)
        self.assertIn("#3 (demo gone.cpp:7): verdict is 'Maybe'", output)


if __name__ == "__main__":
    unittest.main()
