import os
import tempfile
import unittest

from codechecker_integration.diff_runs import (
    _ProjectDelta,
    _by_check,
    _ui_link,
    render_report,
)


def _r(check: str, file: str = "a.cpp", line: int = 1, msg: str = "boom") -> dict:
    return {"checkerId": check, "checkedFile": file, "line": line, "checkerMsg": msg}


class TestByCheck(unittest.TestCase):
    def test_counts_by_check_id(self):
        reports = [_r("modernize-x"), _r("modernize-x"), _r("readability-y")]
        counts = _by_check(reports)
        self.assertEqual(counts, {"modernize-x": 2, "readability-y": 1})

    def test_falls_back_to_checker_name(self):
        reports = [{"checker_name": "bugprone-z"}]
        self.assertEqual(_by_check(reports), {"bugprone-z": 1})

    def test_unknown_when_no_field(self):
        self.assertEqual(_by_check([{}]), {"(unknown)": 1})


class TestUiLink(unittest.TestCase):
    def test_extracts_product_and_appends_filter(self):
        link = _ui_link("https://cc.example/Default", "cppcheck")
        self.assertIn("https://cc.example/Default/reports?", link)
        self.assertIn("run=cppcheck", link)
        self.assertIn("detection-status=New", link)


class TestRenderReport(unittest.TestCase):
    def test_empty_deltas_writes_zero_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "delta.md")
            new_total, resolved_total = render_report(
                [_ProjectDelta(project="cppcheck"), _ProjectDelta(project="curl")],
                "https://cc.example/Default",
                out,
            )
            self.assertEqual(new_total, 0)
            self.assertEqual(resolved_total, 0)
            with open(out) as f:
                content = f.read()
            self.assertIn("0 new, 0 resolved", content)
            self.assertIn("| `cppcheck` | 0 | 0 |", content)

    def test_renders_per_project_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "delta.md")
            deltas = [
                _ProjectDelta(
                    project="cppcheck",
                    new=[_r("modernize-x"), _r("modernize-x"), _r("readability-y")],
                    resolved=[_r("bugprone-z")],
                ),
                _ProjectDelta(project="curl"),
            ]
            new_total, resolved_total = render_report(
                deltas, "https://cc.example/Default", out
            )
            self.assertEqual(new_total, 3)
            self.assertEqual(resolved_total, 1)
            with open(out) as f:
                content = f.read()
            self.assertIn("## `cppcheck`", content)
            self.assertIn("### New (3)", content)
            self.assertIn("### Resolved (1)", content)
            # curl has no deltas, so no detail section emitted
            self.assertNotIn("## `curl`", content)

    def test_caps_examples_per_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "delta.md")
            many = [_r("modernize-x", file=f"f{i}.cpp") for i in range(25)]
            render_report(
                [_ProjectDelta(project="cppcheck", new=many)],
                "https://cc.example/Default",
                out,
            )
            with open(out) as f:
                content = f.read()
            self.assertIn("5 more in UI", content)


if __name__ == "__main__":
    unittest.main()
