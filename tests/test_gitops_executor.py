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


def test_isolated_worktree_can_start_from_base_ref(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-m", "second"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    worktree = IsolatedWorktree.create(tmp_path, base_ref="HEAD~1")
    try:
        assert (worktree.path / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
        assert worktree.base_ref == "HEAD~1"
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


def test_command_runner_docker_preflight_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    runner = CommandRunner(
        sandbox="docker",
        sandbox_config=SandboxConfig(),
        timeout_seconds=10,
    )

    result = runner.run("python -V", tmp_path)

    assert result.returncode == 127
    assert "docker executable" in result.stderr


def test_command_runner_docker_hardening_options(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.invalid/simple")
    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = CommandRunner(
        sandbox="docker",
        sandbox_config=SandboxConfig(
            docker_network="none",
            docker_read_only=True,
            docker_env=("PIP_INDEX_URL", "MISSING_ENV"),
            docker_user="1000:1000",
        ),
        timeout_seconds=10,
    )

    result = runner.run("python -V", tmp_path)

    command = captured["command"]
    assert result.passed
    assert command[0:4] == ["docker", "run", "--rm", "--network"]
    assert "none" in command
    assert "--read-only" in command
    assert command[command.index("--user") + 1] == "1000:1000"
    assert "-e" in command
    assert "PIP_INDEX_URL" in command
    assert "MISSING_ENV" not in command
    assert any(str(tmp_path.resolve()) in part and part.endswith(":ro") for part in command)
