import json
import os
import tempfile
import unittest

from testers.config import Project, load_projects


class TestProject(unittest.TestCase):
    def test_browse_url_with_commit(self):
        p = Project(name="proj", url="https://github.com/org/proj.git", commit="abc123")
        self.assertEqual(p.browse_url, "https://github.com/org/proj/blob/abc123")

    def test_browse_url_without_git_suffix(self):
        p = Project(name="proj", url="https://example.com/proj", commit="abc123")
        self.assertEqual(p.browse_url, "https://example.com/proj/blob/abc123")

    def test_browse_url_falls_back_to_main(self):
        p = Project(name="proj", url="https://example.com/proj.git", commit="")
        self.assertEqual(p.browse_url, "https://example.com/proj/blob/main")


class TestLoadProjects(unittest.TestCase):
    def test_loads_single_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = {
                "projects": {
                    "project": {
                        "url": "https://github.com/project1/project.git",
                        "commit": "abc123",
                    }
                }
            }
            config_path = os.path.join(tmp_dir, "projects.json")
            with open(config_path, "w") as f:
                json.dump(config, f)

            projects = load_projects(config_path)
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0].name, "project")
            self.assertEqual(projects[0].commit, "abc123")

    def test_loads_multiple_projects(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = {
                "projects": {
                    "a": {"url": "https://example.com/a.git", "commit": "aaa"},
                    "b": {"url": "https://example.com/b.git", "commit": "bbb"},
                }
            }
            config_path = os.path.join(tmp_dir, "projects.json")
            with open(config_path, "w") as f:
                json.dump(config, f)

            projects = load_projects(config_path)
            self.assertEqual(len(projects), 2)
            names = {p.name for p in projects}
            self.assertEqual(names, {"a", "b"})

    def test_raises_on_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_projects("/nonexistent/projects.json")

    def test_raises_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "projects.json")
            with open(config_path, "w") as f:
                f.write("not valid json{{{")

            with self.assertRaises(json.JSONDecodeError):
                load_projects(config_path)


if __name__ == "__main__":
    unittest.main()
