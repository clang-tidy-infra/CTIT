"""Guards the wall between the bugfix track and the new-check track."""

import re
import unittest
from pathlib import Path

from pr_watcher.close_finished_issues import BUGFIX_LABEL
from pr_watcher.sync_issues import TRIGGER_LABELS

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
BATCH_WORKFLOW = WORKFLOWS / "bugfix-batch.yaml"


def _job(name):
    """Return the text of one job of the batch workflow."""
    text = BATCH_WORKFLOW.read_text()
    match = re.search(
        rf"^  {name}:\n(.*?)(?=^  \w+:\n|\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, name
    return match.group(1)


class TestIsolation(unittest.TestCase):
    def test_label_starts_no_integration_test(self):
        self.assertNotIn(BUGFIX_LABEL, TRIGGER_LABELS.values())
        self.assertNotIn(BUGFIX_LABEL, (WORKFLOWS / "check-tester.yaml").read_text())

    def test_existing_code_does_not_depend_on_this_track(self):
        sources = [
            *ROOT.glob("*.py"),
            *(ROOT / "pr_watcher").glob("*.py"),
            *(ROOT / "testers").glob("*.py"),
            *(ROOT / "crash_detection").glob("*.py"),
        ]
        self.assertGreater(len(sources), 10)
        for source in sources:
            self.assertNotIn("bugfix_batch", source.read_text(), source.name)

    def test_existing_workflows_do_not_run_this_track(self):
        for workflow in WORKFLOWS.glob("*.yaml"):
            if workflow != BATCH_WORKFLOW:
                self.assertNotIn("bugfix_batch", workflow.read_text(), workflow.name)

    def test_workflow_uses_no_secret(self):
        # Events made with a personal token start workflows, which would let
        # this track trigger check-tester. github.token cannot do that.
        self.assertNotIn("secrets.", BATCH_WORKFLOW.read_text())

    def test_job_running_pull_request_code_cannot_write(self):
        analyze = _job("analyze")
        self.assertNotIn(": write", analyze)
        self.assertNotIn("github.token", analyze)

    def test_job_running_pull_request_code_does_not_save_the_shared_cache(self):
        self.assertIn("actions/cache/restore@", _job("analyze"))
        self.assertNotIn("actions/cache@", _job("analyze"))

    def test_only_the_publish_job_can_write(self):
        self.assertNotIn(": write", _job("select"))
        self.assertIn("issues: write", _job("publish"))


if __name__ == "__main__":
    unittest.main()
