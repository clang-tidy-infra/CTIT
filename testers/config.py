"""Shared project configuration for test projects."""

import json
from dataclasses import dataclass

CONFIG_FILE = "projects.json"
PROJECTS_DIR = "test_projects"


@dataclass
class Project:
    """Project to run clang-tidy checks against."""

    name: str
    url: str
    commit: str

    @property
    def browse_url(self) -> str:
        base_url = self.url.removesuffix(".git")
        ref = self.commit or "main"
        return f"{base_url}/blob/{ref}"


def load_projects(config_path: str = CONFIG_FILE) -> list[Project]:
    with open(config_path) as f:
        config = json.load(f)

    return [
        Project(name=name, url=proj["url"], commit=proj["commit"])
        for name, proj in config["projects"].items()
    ]
