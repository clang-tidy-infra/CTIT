import unittest

from poll_upstream import camel_to_kebab, detect_check, looks_like_new_check


class TestCamelToKebab(unittest.TestCase):
    def test_two_words(self):
        self.assertEqual(camel_to_kebab("ArgumentComment"), "argument-comment")

    def test_single_word(self):
        self.assertEqual(camel_to_kebab("Use"), "use")

    def test_multi_word(self):
        self.assertEqual(camel_to_kebab("UseStaticLambdaCxx"), "use-static-lambda-cxx")

    def test_acronym_treated_per_capital(self):
        # Acronyms aren't special-cased - each capital starts a new word.
        self.assertEqual(camel_to_kebab("UseSTLAlgorithm"), "use-s-t-l-algorithm")


class TestLooksLikeNewCheck(unittest.TestCase):
    def test_canonical_add_check_title(self):
        self.assertTrue(
            looks_like_new_check("[clang-tidy] Add `modernize-use-if-consteval` check")
        )

    def test_add_new_check_phrasing(self):
        self.assertTrue(
            looks_like_new_check(
                "[clang-tidy] Add new check misc-use-braced-initialization"
            )
        )

    def test_lowercase_add(self):
        self.assertTrue(
            looks_like_new_check("[clang-tidy] add new readability check foo")
        )

    def test_rejects_extension(self):
        self.assertFalse(
            looks_like_new_check(
                "[clang-tidy] Extend readability-redundant-parentheses to declarations"
            )
        )

    def test_rejects_bug_fix(self):
        self.assertFalse(
            looks_like_new_check(
                "[clang-tidy] Fix false positive in misc-redundant-expression"
            )
        )

    def test_rejects_option_addition(self):
        # "Adds option ..." - has "add" but no "check" as a whole word.
        self.assertFalse(
            looks_like_new_check(
                "[clang-tidy] Adds `IgnoreMacros` option to cppcoreguidelines-X"
            )
        )

    def test_rejects_checker_word_boundary(self):
        # "checker" must not match \bcheck\b.
        self.assertFalse(
            looks_like_new_check(
                "[clang-tidy] Add checker alias framework and restore aliases"
            )
        )

    def test_rejects_missing_clang_tidy_prefix(self):
        # Without the [clang-tidy] prefix the title is rejected even if it
        # contains both "add" and "check".
        self.assertFalse(looks_like_new_check("Add readability-foo check"))


class TestDetectCheck(unittest.TestCase):
    def test_source_files_drive_name(self):
        files = [
            "clang-tools-extra/clang-tidy/bugprone/ArgumentCommentCheck.cpp",
            "clang-tools-extra/clang-tidy/bugprone/ArgumentCommentCheck.h",
        ]
        self.assertEqual(detect_check(files), "bugprone-argument-comment")

    def test_docs_used_when_no_source(self):
        files = [
            "clang-tools-extra/docs/clang-tidy/checks/modernize/use-ranges.rst",
        ]
        self.assertEqual(detect_check(files), "modernize-use-ranges")

    def test_source_preferred_over_docs(self):
        files = [
            "clang-tools-extra/clang-tidy/modernize/UseRangesCheck.cpp",
            "clang-tools-extra/docs/clang-tidy/checks/other/something-else.rst",
        ]
        self.assertEqual(detect_check(files), "modernize-use-ranges")

    def test_multi_check_picks_alphabetical_first(self):
        files = [
            "clang-tools-extra/clang-tidy/modernize/UseRangesCheck.cpp",
            "clang-tools-extra/clang-tidy/hicpp/UseRangesCheck.cpp",
        ]
        self.assertEqual(detect_check(files), "hicpp-use-ranges")

    def test_no_relevant_files(self):
        files = [
            "clang/lib/Sema/SemaDecl.cpp",
            "README.md",
        ]
        self.assertIsNone(detect_check(files))

    def test_empty_file_list(self):
        self.assertIsNone(detect_check([]))

    def test_ignores_unrelated_source_files(self):
        # ClangTidyCheck.cpp is the base class - it doesn't live in a category
        # subdirectory, so SOURCE_RE doesn't match it.
        files = [
            "clang-tools-extra/clang-tidy/ClangTidyCheck.cpp",
        ]
        self.assertIsNone(detect_check(files))


if __name__ == "__main__":
    unittest.main()
