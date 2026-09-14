import unittest

from pr_watch.find_new_check_prs import (
    added_check_classes,
    added_patch_blocks,
    check_language,
    new_check_names,
    search_recent_prs,
)

TIDY_ROOT = "clang-tools-extra/clang-tidy"
DOCS_ROOT = "clang-tools-extra/docs/clang-tidy/checks"
TESTS_ROOT = "clang-tools-extra/test/clang-tidy/checkers"

BUGPRONE_MODULE_PATCH = """@@ -14,6 +14,7 @@
 #include "SizeofExpressionCheck.h"
+#include "SmartPtrInitializationCheck.h"
 #include "StringConstructorCheck.h"
@@ -50,6 +51,8 @@ class BugproneModule : public ClangTidyModule {
     CheckFactories.registerCheck<SizeofExpressionCheck>(
         "bugprone-sizeof-expression");
+    CheckFactories.registerCheck<SmartPtrInitializationCheck>(
+        "bugprone-smart-ptr-initialization");
     CheckFactories.registerCheck<StringConstructorCheck>(
"""

CERT_MODULE_PATCH = """@@ -30,6 +30,8 @@ class CERTModule : public ClangTidyModule {
+    CheckFactories.registerCheck<bugprone::SmartPtrInitializationCheck>(
+        "cert-mem56-cpp");
"""


REFLOWED_READABILITY_PATCH = """@@ -10,6 +10,7 @@
+#include "RedundantTagCheck.h"
@@ -40,8 +41,12 @@ class ReadabilityModule : public ClangTidyModule {
-    CheckFactories.registerCheck<NonConstParameterCheck>("readability-non-const-parameter");
+    CheckFactories.registerCheck<NonConstParameterCheck>(
+        "readability-non-const-parameter");
+    CheckFactories.registerCheck<RedundantTagCheck>(
+        "readability-redundant-tag");
"""


def _new_check_pr_files():
    """Mirrors llvm/llvm-project#181570: a new check plus a cert alias."""
    return [
        {
            "filename": f"{TIDY_ROOT}/bugprone/BugproneTidyModule.cpp",
            "status": "modified",
            "patch": BUGPRONE_MODULE_PATCH,
        },
        {
            "filename": f"{TIDY_ROOT}/bugprone/SmartPtrInitializationCheck.h",
            "status": "added",
        },
        {
            "filename": f"{TIDY_ROOT}/bugprone/SmartPtrInitializationCheck.cpp",
            "status": "added",
        },
        {
            "filename": f"{TIDY_ROOT}/cert/CERTTidyModule.cpp",
            "status": "modified",
            "patch": CERT_MODULE_PATCH,
        },
        {
            "filename": f"{DOCS_ROOT}/bugprone/smart-ptr-initialization.md",
            "status": "added",
        },
        {"filename": f"{DOCS_ROOT}/cert/mem56-cpp.md", "status": "added"},
        {"filename": f"{DOCS_ROOT}/list.md", "status": "modified"},
        {
            "filename": f"{TESTS_ROOT}/bugprone/smart-ptr-initialization.cpp",
            "status": "added",
        },
    ]


class TestAddedPatchBlocks(unittest.TestCase):
    def test_splits_runs_of_added_lines(self):
        blocks = added_patch_blocks(BUGPRONE_MODULE_PATCH)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], '#include "SmartPtrInitializationCheck.h"')
        self.assertIn("bugprone-smart-ptr-initialization", blocks[1])

    def test_ignores_context_and_removed_lines(self):
        patch = "@@ -1,2 +1,2 @@\n-old line\n context\n+new line\n"
        self.assertEqual(added_patch_blocks(patch), ["new line"])

    def test_ignores_file_header(self):
        patch = "--- a/file\n+++ b/file\n@@ -0,0 +1 @@\n+added\n"
        self.assertEqual(added_patch_blocks(patch), ["added"])

    def test_keeps_added_code_that_itself_starts_with_plus(self):
        patch = "@@ -1,2 +1,3 @@\n context\n+++counter;\n+registerCheck<X>();\n"
        self.assertEqual(added_patch_blocks(patch), ["++counter;\nregisterCheck<X>();"])

    def test_separates_blocks_across_hunks(self):
        patch = "@@ -1 +1 @@\n+first\n@@ -9 +9 @@\n+second\n"
        self.assertEqual(added_patch_blocks(patch), ["first", "second"])


class TestNewCheckNames(unittest.TestCase):
    def test_reports_new_check_and_drops_alias(self):
        self.assertEqual(
            new_check_names(_new_check_pr_files()),
            {"bugprone-smart-ptr-initialization"},
        )

    def test_ignores_pull_request_without_new_check_file(self):
        files = [
            {
                "filename": f"{TIDY_ROOT}/bugprone/SizeofExpressionCheck.cpp",
                "status": "modified",
                "patch": "@@ -1,1 +1,1 @@\n+// fix\n",
            }
        ]
        self.assertEqual(new_check_names(files), set())

    def test_ignores_registrations_only_touched_by_clang_format(self):
        """llvm/llvm-project#210007 reflowed ten neighbouring registrations."""
        files = [
            {
                "filename": f"{TIDY_ROOT}/readability/ReadabilityTidyModule.cpp",
                "status": "modified",
                "patch": REFLOWED_READABILITY_PATCH,
            },
            {
                "filename": f"{TIDY_ROOT}/readability/RedundantTagCheck.h",
                "status": "added",
            },
        ]
        self.assertEqual(new_check_names(files), {"readability-redundant-tag"})

    def test_falls_back_to_docs_when_patch_is_missing(self):
        files = [
            {
                "filename": f"{TIDY_ROOT}/performance/PerformanceTidyModule.cpp",
                "status": "modified",
            },
            {
                "filename": f"{TIDY_ROOT}/performance/InefficientSubstrCheck.h",
                "status": "added",
            },
            {
                "filename": f"{DOCS_ROOT}/performance/inefficient-substr.rst",
                "status": "added",
            },
            {"filename": f"{DOCS_ROOT}/cert/oop11-cpp.rst", "status": "added"},
        ]
        self.assertEqual(new_check_names(files), {"performance-inefficient-substr"})


class TestAddedCheckClasses(unittest.TestCase):
    def test_collects_headers_and_sources(self):
        files = [
            {
                "filename": f"{TIDY_ROOT}/bugprone/SmartPtrInitializationCheck.cpp",
                "status": "added",
            },
            {
                "filename": f"{TIDY_ROOT}/bugprone/SizeofExpressionCheck.cpp",
                "status": "modified",
            },
        ]
        self.assertEqual(
            added_check_classes(files),
            {("bugprone", "SmartPtrInitializationCheck")},
        )


class TestCheckLanguage(unittest.TestCase):
    def test_uses_c_when_every_new_test_is_c(self):
        files = [
            {
                "filename": f"{TESTS_ROOT}/bugprone/custom-errno-declaration.c",
                "status": "added",
            }
        ]
        language = check_language(files, "bugprone-custom-errno-declaration")
        self.assertEqual(language, "c")

    def test_uses_cpp_when_any_new_test_is_cpp(self):
        files = [
            {
                "filename": f"{TESTS_ROOT}/misc/redundant-expression.c",
                "status": "added",
            },
            {
                "filename": f"{TESTS_ROOT}/misc/redundant-expression-cxx17.cpp",
                "status": "added",
            },
        ]
        self.assertEqual(check_language(files, "misc-redundant-expression"), "cpp")

    def test_defaults_to_cpp_without_tests(self):
        self.assertEqual(check_language([], "modernize-use-bit-cast"), "cpp")

    def test_ignores_tests_of_another_check(self):
        files = [
            {"filename": f"{TESTS_ROOT}/bugprone/other-check.c", "status": "added"}
        ]
        self.assertEqual(check_language(files, "bugprone-smart-ptr"), "cpp")


class FakeSearchClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.queries = []

    def paginate(self, path, params=None, items_key=None):
        self.queries.append((params or {}).get("q", ""))
        return self.pages.pop(0)


class TestSearchRecentPrs(unittest.TestCase):
    def test_unions_filters_and_sorts_by_activity(self):
        client = FakeSearchClient(
            [
                [{"number": 1, "updated_at": "2026-09-13T00:00:00Z", "draft": False}],
                [
                    {"number": 1, "updated_at": "2026-09-13T00:00:00Z", "draft": False},
                    {"number": 2, "updated_at": "2026-09-13T10:00:00Z", "draft": False},
                ],
            ]
        )
        prs = search_recent_prs(
            client, "llvm/llvm-project", "2026-09-12T00:00:00Z", False
        )
        self.assertEqual([pull["number"] for pull in prs], [2, 1])
        self.assertEqual(len(client.queries), 2)
        for query in client.queries:
            self.assertIn("repo:llvm/llvm-project is:pr is:open", query)
            self.assertIn("updated:>=2026-09-12T00:00:00Z", query)

    def test_drops_drafts_unless_requested(self):
        pages = [
            [{"number": 3, "updated_at": "2026-09-13T00:00:00Z", "draft": True}],
            [],
        ]
        self.assertEqual(
            search_recent_prs(FakeSearchClient(pages), "r", "since", False), []
        )
        self.assertEqual(
            len(search_recent_prs(FakeSearchClient(list(pages)), "r", "since", True)), 1
        )


if __name__ == "__main__":
    unittest.main()
