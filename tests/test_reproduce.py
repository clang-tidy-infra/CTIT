import json
import os
import stat
import tempfile
import unittest

from testers.reproduce import reproduce

# A stand-in clang-tidy that prints the reproducer's `// out:` lines, with
# FILE replaced by the file name, followed by its own name, so the test can
# tell the patched and baseline outputs apart.
FAKE_TIDY = """#!/bin/sh
for arg; do case "$arg" in *.c|*.cpp) file=$arg;; esac; done
sed -n "s|^// out: ||p" "$file" | sed "s|FILE|$file|"
echo "ran $(basename "$0")"
"""


class TestReproduce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        os.makedirs("logs")
        with open("logs/demo.log", "w") as log:
            log.write(
                "/w/test_projects/demo/a.cpp:3:1: warning: first [check-a]\n"
                "/w/test_projects/demo/b.cpp:5:1: warning: second [check-a]\n"
                "/w/test_projects/demo/c.cpp:7:1: warning: third [check-a]\n"
            )
        os.makedirs("reproducers")
        for name in ("patched-tidy", "baseline-tidy"):
            with open(name, "w") as script:
                script.write(FAKE_TIDY)
            os.chmod(name, os.stat(name).st_mode | stat.S_IEXEC)

    def write(self, name: str, text: str) -> None:
        with open(os.path.join("reproducers", name), "w") as source:
            source.write(text)

    def collect(self, **kwargs) -> list[dict]:
        args = {
            "sources": [],
            "repro_dir": "reproducers",
            "log_dir": "logs",
            "check_name": "check-a",
            "tidy_config": None,
            "clang_tidy_bin": os.path.abspath("patched-tidy"),
            "baseline_bin": os.path.abspath("baseline-tidy"),
            "baseline_unavailable": False,
        }
        args.update(kwargs)
        reproduce(**args)
        with open("reproducers.json") as result:
            return json.load(result)

    def test_keeps_only_reproducers_of_their_rows_check(self):
        self.write("2.cpp", "// out: FILE:1:1: warning: second [check-a]\n")
        # Warns, but from another check than the row's.
        self.write("1.cpp", "// out: FILE:1:1: warning: other [check-b]\n")
        # Warns from the right check, but does not compile.
        self.write(
            "3.cpp",
            "// out: FILE:1:1: warning: third [check-a]\n"
            "// out: FILE:2:1: error: no such type [clang-diagnostic-error]\n",
        )
        # Not named after a row.
        self.write("9.cpp", "// out: FILE:1:1: warning: x [check-a]\n")

        saved = self.collect()

        self.assertEqual([[w["row"] for w in r["warnings"]] for r in saved], [[2]])
        repro = saved[0]
        target = repro["warnings"][0]
        self.assertEqual((target["file"], target["line"]), ("b.cpp", 5))
        self.assertIn("2.cpp:1:1: warning: second [check-a]", repro["patched_output"])
        self.assertIn("ran patched-tidy", repro["patched_output"])
        self.assertEqual(repro["baseline_status"], "ran")
        self.assertIn("ran baseline-tidy", repro["baseline_output"])
        with open("reproducers.md") as markdown:
            self.assertIn("ran baseline-tidy", markdown.read())

    def test_baseline_states_without_a_baseline_binary(self):
        self.write("1.cpp", "// out: FILE:1:1: warning: first [check-a]\n")
        for unavailable, status in ((True, "unavailable"), (False, "not-requested")):
            with self.subTest(status=status):
                saved = self.collect(
                    baseline_bin=None, baseline_unavailable=unavailable
                )
                self.assertEqual(saved[0]["baseline_status"], status)
                self.assertIsNone(saved[0]["baseline_output"])
                with open("reproducers.md") as markdown:
                    text = markdown.read()
                self.assertNotIn("Baseline clang-tidy:\n", text)
                self.assertEqual("check unavailable" in text, unavailable)

    def test_directive_lines(self):
        self.write(
            "1.c",
            "// ctit-rows: 3\n// ctit-args: -std=c99 -DX\n"
            "// out: FILE:1:1: warning: first [check-a]\n",
        )
        saved = self.collect()
        self.assertEqual(saved[0]["compiler_args"], ["-std=c99", "-DX"])
        self.assertEqual(saved[0]["language"], "c")
        self.assertEqual([w["row"] for w in saved[0]["warnings"]], [1, 3])

    def test_one_reproducer_for_several_rows(self):
        # Rows 1-3 share a cause; 3.cpp repeats row 3 and adds nothing new.
        self.write(
            "1.cpp", "// ctit-rows: 2-3\n// out: FILE:1:1: warning: x [check-a]\n"
        )
        self.write("3.cpp", "// out: FILE:1:1: warning: x [check-a]\n")
        saved = self.collect()
        self.assertEqual(len(saved), 1)
        self.assertEqual(
            [(w["row"], w["file"]) for w in saved[0]["warnings"]],
            [(1, "a.cpp"), (2, "b.cpp"), (3, "c.cpp")],
        )
        with open("reproducers.md") as markdown:
            text = markdown.read()
        self.assertIn("#### Reproducer 1: 3 warnings", text)
        self.assertIn("- #3 demo: `c.cpp:7` third", text)
        self.assertEqual(text.count("Patched clang-tidy:"), 1)

    def test_rejects_rows_of_a_check_it_does_not_reproduce(self):
        with open("logs/demo.log", "a") as log:
            log.write("/w/test_projects/demo/d.cpp:9:1: warning: fourth [check-b]\n")
        self.write("1.cpp", "// ctit-rows: 4\n// out: FILE:1:1: warning: x [check-a]\n")
        self.assertEqual(self.collect(check_name="check-a,check-b"), [])
        self.write(
            "1.cpp",
            "// ctit-rows: 4\n// out: FILE:1:1: warning: x [check-a]\n"
            "// out: FILE:2:1: warning: y [check-b]\n",
        )
        saved = self.collect(check_name="check-a,check-b")
        self.assertEqual([w["row"] for w in saved[0]["warnings"]], [1, 4])


if __name__ == "__main__":
    unittest.main()
