import subprocess
import sys

from issue_agent.config import config_from_mapping
from issue_agent.issue import Issue
from issue_agent.models import ModelResponse
from issue_agent.solver import IssueSolver

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


class FakeOpenAIClient:
    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        text = '{"files": ["app.py"]}' if self.config.name == "triage" else PATCH
        return ModelResponse(
            text=text,
            provider=self.config.name,
            model=self.config.model,
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.01,
        )


def _init_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_solver_uses_worktree_and_returns_diff(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    check = (
        f"{sys.executable} -c "
        "\"from pathlib import Path; assert Path('app.py').read_text() == 'VALUE = 2\\n'\""
    )
    config = config_from_mapping({"checks": {"commands": [check]}})
    solver = IssueSolver(config=config, sandbox="local", model_profile=None, max_iters=3)

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    assert result.resolved
    assert result.status == "resolved"
    assert "+VALUE = 2" in result.diff
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert result.metadata["attempt_count"] == 1
    assert result.metadata["cost_usd"] == 0.02
    assert result.metadata["triage"]["provider"] == "triage"
