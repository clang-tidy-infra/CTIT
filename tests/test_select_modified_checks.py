import os
import subprocess
import tempfile
import unittest

from crash_detection.select_modified_checks import (
    SelectionResult,
    format_ci_output,
    format_clang_tidy_checks,
    parse_registrations,
    select_modified_checks,
)

TIDY_ROOT = "clang-tools-extra/clang-tidy"


class TestParseRegistrations(unittest.TestCase):
    def test_keys_registration_by_tidy_module_directory(self):
        source = """
#include "UseAutoCheck.h"

CheckFactories.registerCheck<UseAutoCheck>(
    "modernize-use-auto");
"""
        registrations = parse_registrations(
            source, f"{TIDY_ROOT}/modernize/ModernizeTidyModule.cpp"
        )
        self.assertEqual(len(registrations), 1)
        registration = next(iter(registrations))
        self.assertEqual(registration.module, "modernize")
        self.assertEqual(registration.class_name, "UseAutoCheck")
        self.assertEqual(registration.check_name, "modernize-use-auto")


class GitFixture:
    def __init__(self, root: str):
        self.root = root
        subprocess.run(["git", "init", "-q", root], check=True)
        subprocess.run(["git", "-C", root, "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", root, "config", "user.email", "test@example.com"],
            check=True,
        )

    def write(self, path: str, content: str) -> None:
        full_path = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as file:
            file.write(content)

    def commit(self, subject: str) -> str:
        subprocess.run(["git", "-C", self.root, "add", "."], check=True)
        subprocess.run(
            ["git", "-C", self.root, "commit", "-q", "-m", subject], check=True
        )
        return subprocess.run(
            ["git", "-C", self.root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()


class TestSelectModifiedChecks(unittest.TestCase):
    def _base_fixture(self, root: str) -> tuple[GitFixture, str]:
        fixture = GitFixture(root)
        fixture.write(
            f"{TIDY_ROOT}/modernize/UseAutoCheck.h", "class UseAutoCheck {};\n"
        )
        fixture.write(
            f"{TIDY_ROOT}/modernize/UseAutoCheck.cpp",
            '#include "UseAutoCheck.h"\n',
        )
        fixture.write(
            f"{TIDY_ROOT}/modernize/ModernizeTidyModule.cpp",
            """
#include "UseAutoCheck.h"
void registerChecks() {
  CheckFactories.registerCheck<UseAutoCheck>("modernize-use-auto");
}
""",
        )
        fixture.write(
            f"{TIDY_ROOT}/hicpp/HICPPTidyModule.cpp",
            """
#include "../modernize/UseAutoCheck.h"
void registerChecks() {
  CheckFactories.registerCheck<modernize::UseAutoCheck>("hicpp-use-auto");
}
""",
        )
        return fixture, fixture.commit("initial")

    def test_selects_primary_check_not_alias(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                f"{TIDY_ROOT}/modernize/UseAutoCheck.cpp",
                '#include "UseAutoCheck.h"\n// changed\n',
            )
            head = fixture.commit("Change use-auto")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, {"modernize-use-auto"})
            self.assertEqual(result.changed_utils, set())

    def test_selects_check_regardless_of_commit_subject(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                f"{TIDY_ROOT}/modernize/UseAutoCheck.cpp",
                '#include "UseAutoCheck.h"\n// changed\n',
            )
            head = fixture.commit("[clangd][clang-tidy] Change shared behavior")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, {"modernize-use-auto"})

    def test_module_only_change_selects_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                f"{TIDY_ROOT}/modernize/ModernizeTidyModule.cpp",
                """
#include "UseAutoCheck.h"
// Registration order or unrelated module metadata changed.
void registerChecks() {
  CheckFactories.registerCheck<UseAutoCheck>("modernize-use-auto");
}
""",
            )
            head = fixture.commit("Change module metadata")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, set())
            self.assertEqual(result.changed_utils, set())

    def test_registration_change_selects_new_check(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                f"{TIDY_ROOT}/readability/NewThingCheck.h",
                "class NewThingCheck {};\n",
            )
            fixture.write(
                f"{TIDY_ROOT}/readability/NewThingCheck.cpp",
                '#include "NewThingCheck.h"\n',
            )
            fixture.write(
                f"{TIDY_ROOT}/readability/ReadabilityTidyModule.cpp",
                """
#include "NewThingCheck.h"
CheckFactories.registerCheck<NewThingCheck>(
    "readability-new-thing");
""",
            )
            head = fixture.commit("Add new-thing")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, {"readability-new-thing"})

    def test_maps_registered_class_when_file_stem_differs(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                f"{TIDY_ROOT}/llvm/HeaderGuardCheck.h",
                "class LLVMHeaderGuardCheck : public ClangTidyCheck {};\n",
            )
            fixture.write(
                f"{TIDY_ROOT}/llvm/HeaderGuardCheck.cpp",
                '#include "HeaderGuardCheck.h"\n',
            )
            fixture.write(
                f"{TIDY_ROOT}/llvm/LLVMTidyModule.cpp",
                """
#include "HeaderGuardCheck.h"
CheckFactories.registerCheck<LLVMHeaderGuardCheck>("llvm-header-guard");
""",
            )
            base = fixture.commit("Add header-guard")
            fixture.write(
                f"{TIDY_ROOT}/llvm/HeaderGuardCheck.cpp",
                '#include "HeaderGuardCheck.h"\n// changed\n',
            )
            head = fixture.commit("Fix header-guard")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, {"llvm-header-guard"})

    def test_shared_utility_is_reported_but_not_selected(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(f"{TIDY_ROOT}/utils/TypeTraits.cpp", "// shared change\n")
            head = fixture.commit("Change shared helper")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, set())
            self.assertEqual(
                result.changed_utils,
                {f"{TIDY_ROOT}/utils/TypeTraits.cpp"},
            )

    def test_test_only_commit_selects_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                "clang-tools-extra/test/clang-tidy/checkers/modernize/use-auto.cpp",
                "// regression test only\n",
            )
            head = fixture.commit("Add regression test. NFC")

            result = select_modified_checks(root, base, head)

            self.assertEqual(result.changed_checks, set())
            self.assertEqual(result.changed_utils, set())

    def test_ci_report_lists_checks_and_utils(self):
        with tempfile.TemporaryDirectory() as root:
            fixture, base = self._base_fixture(root)
            fixture.write(
                f"{TIDY_ROOT}/modernize/UseAutoCheck.cpp",
                '#include "UseAutoCheck.h"\n// changed\n',
            )
            fixture.write(f"{TIDY_ROOT}/utils/TypeTraits.cpp", "// shared change\n")
            head = fixture.commit("Change check and util")

            result = select_modified_checks(root, base, head)
            report = format_ci_output(result)

            self.assertIn("has_checks=true", report)
            self.assertIn("check_name=modernize-use-auto", report)
            self.assertIn("checks=-*,modernize-use-auto", report)
            self.assertIn(f"changed_utils={TIDY_ROOT}/utils/TypeTraits.cpp", report)


class TestCiOutputs(unittest.TestCase):
    def test_clang_tidy_checks_glob(self):
        self.assertEqual(format_clang_tidy_checks(set()), "")
        self.assertEqual(
            format_clang_tidy_checks({"b-check", "a-check"}),
            "-*,a-check,b-check",
        )

    def test_format_ci_output_writes_github_output(self):
        result = SelectionResult(
            base="aaa",
            head="bbb",
            changed_checks={"b-check", "a-check"},
        )
        previous = os.environ.get("GITHUB_OUTPUT")
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as handle:
            path = handle.name
        try:
            os.environ["GITHUB_OUTPUT"] = path
            text = format_ci_output(result)
            with open(path, encoding="utf-8") as handle:
                written = handle.read()
        finally:
            if previous is None:
                os.environ.pop("GITHUB_OUTPUT", None)
            else:
                os.environ["GITHUB_OUTPUT"] = previous
            os.unlink(path)

        self.assertEqual(text + "\n", written)
        self.assertIn("has_checks=true\n", text)
        self.assertIn("check_name=a-check,b-check\n", text)
        self.assertIn("checks=-*,a-check,b-check\n", text)


if __name__ == "__main__":
    unittest.main()
