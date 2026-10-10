import unittest

from crash_detection.parse_check_profile import combine_profiles, parse_profile

PROFILE = [
    "===-------------------------------------------------------------------------===\n",
    "                          clang-tidy checks profiling\n",
    "===-------------------------------------------------------------------------===\n",
    "  Total Execution Time: 3.0000 seconds (3.5000 wall clock)\n",
    "\n",
    "   ---User Time---    --System Time--    --User+System--    ---Wall Time---   --- Name ---\n",
    "    2.0000 ( 66.7%)    0.0000 (  0.0%)    2.0000 ( 66.7%)    2.5000 ( 71.4%)  check-a\n",
    "    1.0000 ( 33.3%)    0.0000 (  0.0%)    1.0000 ( 33.3%)    1.0000 ( 28.6%)  check-b\n",
    "    3.0000 (100.0%)    0.0000 (  0.0%)    3.0000 (100.0%)    3.5000 (100.0%)  Total\n",
]


class TestParseProfile(unittest.TestCase):
    def test_reads_wall_time_per_check(self):
        total, checks = parse_profile(["warning before the profile\n", *PROFILE])
        self.assertEqual(total, 3.5)
        self.assertEqual(checks, {"check-a": 2.5, "check-b": 1.0})

    def test_no_profile(self):
        self.assertEqual(parse_profile(["just a warning\n"]), (0.0, {}))


class TestCombineProfiles(unittest.TestCase):
    def test_sums_checks_over_projects(self):
        profiles = {
            "one": (3.5, {"check-a": 2.5, "check-b": 1.0}),
            "two": (1.0, {"check-a": 0.5, "check-c": 0.5}),
        }
        self.assertEqual(
            combine_profiles(profiles),
            {"check-a": 3.0, "check-b": 1.0, "check-c": 0.5},
        )


if __name__ == "__main__":
    unittest.main()
