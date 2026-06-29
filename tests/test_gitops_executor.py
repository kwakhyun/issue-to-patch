import subprocess
import sys

from issue_agent.config import SandboxConfig
from issue_agent.executor import CommandRunner
from issue_agent.gitops import IsolatedWorktree, current_diff, is_dirty


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


def test_isolated_worktree_does_not_modify_original(tmp_path):
    _init_repo(tmp_path)

    worktree = IsolatedWorktree.create(tmp_path)
    try:
        (worktree.path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

        assert "VALUE = 2" in current_diff(worktree.path)
        assert not is_dirty(tmp_path)
    finally:
        worktree.cleanup()


def test_command_runner_local_success(tmp_path):
    runner = CommandRunner(
        sandbox="local",
        sandbox_config=SandboxConfig(),
        timeout_seconds=10,
    )

    result = runner.run(f"{sys.executable} -c 'print(123)'", tmp_path)

    assert result.passed
    assert result.stdout.strip() == "123"
