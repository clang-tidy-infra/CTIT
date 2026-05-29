import os
import sys
import tempfile
import unittest

from slim_comment import GITHUB_COMMENT_LIMIT, slim_comment

ARTIFACT_URL = "https://github.com/org/repo/actions/runs/1/artifacts/2"

_SUMMARY = """\
### Clang-Tidy Integration Test Results

| Project | Status | Warnings | Errors | Crash |
| :--- | :--- | :--- | :--- | :--- |
| **cppcheck** | ⚠️ Warnings | 3 | 0 | - |
| **poco** | ✅ Pass | 0 | 0 | - |

---
"""

_PROJECT_DETAILS = """\
<details>
<summary><strong>cppcheck Details (3 warnings, 0 errors)</strong></summary>

#### ⚠️ [lib/token.cpp:10](https://github.com/danmar/cppcheck/blob/main/lib/token.cpp#L10)
bad usage `[misc-use-braced-initialization]`
  ```cpp
  int x = foo();
  ```

</details>
"""

_AI_ANALYSIS = """\
<details>
<summary><b>AI False-Positive Analysis</b> (click to expand)</summary>

| # | Project | Location | Check | Verdict | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | cppcheck | lib/token.cpp:10 | misc-use-braced-initialization | TP | clearly wrong |

**Summary**: 1 True Positive, 0 False Positives, 0 Uncertain out of 1 total warnings.

</details>
"""

# Small enough to fit within the GitHub limit.
SMALL_REPORT = _SUMMARY + "\n" + _PROJECT_DETAILS + "\n" + _AI_ANALYSIS


def _huge_ai() -> str:
    return (
        "<details>\n<summary><b>AI False-Positive Analysis</b> (click to expand)</summary>\n"
        + "x" * GITHUB_COMMENT_LIMIT
        + "\n</details>\n"
    )


def _huge_project_details() -> str:
    return (
        "<details>\n<summary><strong>cppcheck Details (9999 warnings, 0 errors)</strong></summary>\n"
        + "x" * GITHUB_COMMENT_LIMIT
        + "\n</details>\n"
    )


class TestSlimComment(unittest.TestCase):
    def test_fits_returned_unchanged(self):
        result = slim_comment(SMALL_REPORT, ARTIFACT_URL)
        self.assertEqual(result, SMALL_REPORT)
        self.assertIn("cppcheck Details", result)
        self.assertIn("AI False-Positive Analysis", result)

    def test_huge_ai_is_stripped(self):
        content = _SUMMARY + "\n" + _PROJECT_DETAILS + "\n" + _huge_ai()
        assert len(content) > GITHUB_COMMENT_LIMIT
        result = slim_comment(content, ARTIFACT_URL)
        self.assertNotIn("AI False-Positive Analysis", result)
        self.assertIn("cppcheck Details", result)
        self.assertIn(
            f"[Full per-project details in workflow artifacts]({ARTIFACT_URL})",
            result,
        )
        self.assertLessEqual(len(result), GITHUB_COMMENT_LIMIT)

    def test_huge_ai_and_findings_both_stripped(self):
        content = _SUMMARY + "\n" + _huge_project_details() + "\n" + _huge_ai()
        assert len(content) > GITHUB_COMMENT_LIMIT
        result = slim_comment(content, ARTIFACT_URL)
        self.assertNotIn("AI False-Positive Analysis", result)
        self.assertNotIn("cppcheck Details", result)

    def test_huge_findings_alone_triggers_slim(self):
        content = _SUMMARY + "\n" + _huge_project_details()
        result = slim_comment(content, ARTIFACT_URL)
        self.assertNotIn("cppcheck Details", result)
        self.assertIn(ARTIFACT_URL, result)

    def test_slim_keeps_summary_table(self):
        content = _SUMMARY + "\n" + _huge_project_details() + "\n" + _huge_ai()
        result = slim_comment(content, ARTIFACT_URL)
        self.assertIn("Clang-Tidy Integration Test Results", result)
        self.assertIn("| **cppcheck** |", result)
        self.assertTrue(result.endswith("\n"))

    def test_no_details_blocks_fits(self):
        result = slim_comment(_SUMMARY, ARTIFACT_URL)
        self.assertEqual(result, _SUMMARY)

    def test_empty_content_fits(self):
        result = slim_comment("", ARTIFACT_URL)
        self.assertEqual(result, "")

    def test_exactly_at_limit_fits(self):
        content = "x" * GITHUB_COMMENT_LIMIT
        result = slim_comment(content, ARTIFACT_URL)
        self.assertEqual(result, content)

    def test_one_over_limit_triggers_slimming(self):
        content = "x" * (GITHUB_COMMENT_LIMIT + 1)
        result = slim_comment(content, ARTIFACT_URL)
        self.assertIn(ARTIFACT_URL, result)


class TestSlimCommentCLI(unittest.TestCase):
    def _run(self, content: str, artifact_url: str) -> tuple[str, str, int]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "issue.md")
            with open(path, "w") as f:
                f.write(content)

            import subprocess

            proc = subprocess.run(
                [sys.executable, "slim_comment.py", path, artifact_url],
                capture_output=True,
                text=True,
            )
            result_content = ""
            if os.path.exists(path):
                with open(path) as f:
                    result_content = f.read()
            return result_content, proc.stderr, proc.returncode

    def test_small_report_unchanged(self):
        content, _, code = self._run(SMALL_REPORT, ARTIFACT_URL)
        self.assertEqual(code, 0)
        self.assertEqual(content, SMALL_REPORT)

    def test_large_report_edits_file_in_place(self):
        large = _SUMMARY + "\n" + _huge_project_details() + "\n" + _huge_ai()
        content, _, code = self._run(large, ARTIFACT_URL)
        self.assertEqual(code, 0)
        self.assertNotIn("AI False-Positive Analysis", content)
        self.assertIn(ARTIFACT_URL, content)

    def test_missing_file_exits_nonzero(self):
        import subprocess

        proc = subprocess.run(
            [sys.executable, "slim_comment.py", "/nonexistent/issue.md", ARTIFACT_URL],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Error reading", proc.stderr)

    def test_warns_when_still_over_limit(self):
        # No <details> blocks, raw content over limit — can't slim further.
        huge = "x" * (GITHUB_COMMENT_LIMIT + 1)
        _, stderr, code = self._run(huge, ARTIFACT_URL)
        self.assertEqual(code, 0)
        self.assertIn("Warning", stderr)


if __name__ == "__main__":
    unittest.main()
