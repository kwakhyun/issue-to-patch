import subprocess
import sys
from pathlib import Path

from issue_agent.config import config_from_mapping
from issue_agent.errors import GiaError, ModelError
from issue_agent.executor import CommandResult
from issue_agent.issue import Issue
from issue_agent.models import ModelResponse
from issue_agent.solver import AttemptRecord, IssueSolver, SolveOptions

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""

PATCH_THREE = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 3
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


class FallbackOpenAIClient:
    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        if self.config.name == "triage":
            text = '{"files": ["app.py"]}'
        elif self.config.name == "coder":
            raise ModelError("coder unavailable")
        else:
            text = PATCH
        return ModelResponse(
            text=text,
            provider=self.config.name,
            model=self.config.model,
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.01,
        )


class RepairOpenAIClient:
    patch_calls = 0

    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        if self.config.name == "triage":
            text = '{"files": ["app.py"]}'
        else:
            type(self).patch_calls += 1
            text = PATCH if self.patch_calls == 1 else PATCH_THREE
        return ModelResponse(text=text, provider=self.config.name, model=self.config.model)


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
    solver = IssueSolver(config=config, options=SolveOptions(sandbox="local", max_iters=3))

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
    assert result.metadata["schema_version"] == "gia.solve.v2"
    assert result.metadata["model_profile"] == "coder:Qwen/Qwen3-Coder-30B-A3B-Instruct"
    assert result.metadata["requested_model_profile"] is None
    assert result.metadata["model_provider"] == "coder"
    assert result.metadata["model"] == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    assert result.metadata["input_tokens"] == 20
    assert result.metadata["output_tokens"] == 40
    assert result.metadata["model_route"] == [
        {
            "provider": "coder",
            "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
            "key": "coder:Qwen/Qwen3-Coder-30B-A3B-Instruct",
        }
    ]
    assert result.metadata["triage"]["provider"] == "triage"
    assert result.metadata["allow_dirty"] is False
    assert result.metadata["base_ref"] == "HEAD"
    assert result.metadata["kept_worktree"] is False
    assert not Path(result.metadata["worktree_path"]).exists()
    assert result.attempts[0].patch_dry_run_passed
    assert result.attempts[0].failure_stage is None


def test_solver_refuses_dirty_repo_by_default(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    (tmp_path / "app.py").write_text("VALUE = 99\n", encoding="utf-8")
    config = config_from_mapping({"checks": {"commands": [f"{sys.executable} -c 'pass'"]}})
    solver = IssueSolver(config=config, options=SolveOptions(sandbox="local", max_iters=1))

    try:
        solver.solve(
            repo=tmp_path,
            issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
        )
    except GiaError as exc:
        assert "--allow-dirty" in str(exc)
    else:
        raise AssertionError("dirty repo should be rejected")


def test_solver_rejects_invalid_config_before_worktree_creation(tmp_path):
    config = config_from_mapping({"router": {"coder_model": "missing"}})

    try:
        IssueSolver(config=config, options=SolveOptions(sandbox="local"))
    except GiaError as exc:
        assert "router.coder_model" in str(exc)
    else:
        raise AssertionError("invalid config should be rejected")


def test_solver_allows_dirty_repo_when_explicit(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    (tmp_path / "notes.txt").write_text("local note\n", encoding="utf-8")
    check = f"{sys.executable} -c 'pass'"
    config = config_from_mapping({"checks": {"commands": [check]}})
    solver = IssueSolver(
        config=config,
        options=SolveOptions(sandbox="local", max_iters=1, allow_dirty=True),
    )

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    assert result.resolved
    assert result.metadata["original_dirty"] is True
    assert result.metadata["allow_dirty"] is True


def test_solver_skip_checks_records_unchecked(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    config = config_from_mapping(
        {"checks": {"commands": [f"{sys.executable} -c 'raise SystemExit(1)'"]}}
    )
    solver = IssueSolver(
        config=config,
        options=SolveOptions(sandbox="local", max_iters=1, skip_checks=True),
    )

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    assert not result.resolved
    assert result.status == "unchecked"
    assert result.metadata["checks_skipped"] is True
    assert result.attempts[0].patch_applied
    assert result.attempts[0].check_results == []


def test_solver_empty_checks_records_unchecked(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    config = config_from_mapping({"checks": {"commands": []}})
    solver = IssueSolver(
        config=config,
        options=SolveOptions(sandbox="local", max_iters=1),
    )

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    assert not result.resolved
    assert result.status == "unchecked"
    assert result.attempts[0].failure_stage == "checks"
    assert result.attempts[0].error == "no_checks_configured"


def test_solver_replacement_repairs_are_applied_against_base(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    RepairOpenAIClient.patch_calls = 0
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", RepairOpenAIClient)
    check = (
        f"{sys.executable} -c "
        "\"from pathlib import Path; assert Path('app.py').read_text() == 'VALUE = 3\\n'\""
    )
    config = config_from_mapping({"checks": {"commands": [check]}})
    solver = IssueSolver(
        config=config,
        options=SolveOptions(sandbox="local", max_iters=2, repair_strategy="replacement"),
    )

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 3", source="test"),
    )

    assert result.resolved
    assert result.metadata["repair_strategy"] == "replacement"
    assert result.metadata["attempt_count"] == 2
    assert "+VALUE = 3" in result.diff
    assert "+VALUE = 2" not in result.diff


def test_solver_records_fallback_provider_metadata(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FallbackOpenAIClient)
    config = config_from_mapping(
        {
            "providers": {
                "fallback": {
                    "base_url": "http://localhost:8001/v1",
                    "model": "fallback",
                }
            },
            "router": {"fallback_model": "fallback"},
            "checks": {"commands": [f"{sys.executable} -c 'pass'"]},
        }
    )
    solver = IssueSolver(config=config, options=SolveOptions(sandbox="local", max_iters=1))

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    assert result.resolved
    assert result.metadata["patch_provider"] == "fallback"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["patch_provider_errors"][0]["provider"] == "coder"


def test_solver_keep_worktree_policies(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    config = config_from_mapping({"checks": {"commands": [f"{sys.executable} -c 'pass'"]}})
    solver = IssueSolver(
        config=config,
        options=SolveOptions(sandbox="local", max_iters=1, keep_worktree="always"),
    )

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    try:
        assert result.resolved
        assert result.metadata["kept_worktree"] is True
        assert Path(result.metadata["worktree_path"]).exists()
    finally:
        _cleanup_kept_worktree(
            tmp_path, result.metadata["worktree_path"], result.metadata["worktree_branch"]
        )


def test_solver_keep_worktree_on_failure(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    config = config_from_mapping(
        {"checks": {"commands": [f"{sys.executable} -c 'raise SystemExit(1)'"]}}
    )
    solver = IssueSolver(
        config=config,
        options=SolveOptions(sandbox="local", max_iters=1, keep_worktree="on-failure"),
    )

    result = solver.solve(
        repo=tmp_path,
        issue=Issue(title="Update value", body="Change VALUE to 2", source="test"),
    )

    try:
        assert not result.resolved
        assert result.metadata["kept_worktree"] is True
        assert Path(result.metadata["worktree_path"]).exists()
    finally:
        _cleanup_kept_worktree(
            tmp_path, result.metadata["worktree_path"], result.metadata["worktree_branch"]
        )


def test_attempt_record_can_include_check_outputs():
    record = AttemptRecord(
        iteration=1,
        provider="p",
        model="m",
        patch_valid=True,
        patch_dry_run_passed=True,
        patch_applied=True,
        checks_passed=False,
        failure_stage="checks",
        error="checks_failed",
        cost_usd=0.0,
        input_tokens=0,
        output_tokens=0,
        check_results=[
            CommandResult(
                command="pytest",
                returncode=1,
                stdout="token=super-secret-value " + ("x" * 80),
                stderr="Authorization: Bearer abcdefghijklmnop",
                duration_seconds=0.1,
                sandbox="local",
            )
        ],
    )

    compact = record.to_json()
    detailed = record.to_json(include_outputs=True, output_limit=32)

    assert "stdout" not in compact["checks"][0]
    assert "[REDACTED]" in detailed["checks"][0]["stdout"]
    assert "truncated" in detailed["checks"][0]["stdout"]
    assert detailed["checks"][0]["stderr"] == "Authorization: Bearer [REDACTED]"


def _cleanup_kept_worktree(repo, path, branch):
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", str(branch)],
        cwd=repo,
        check=False,
        capture_output=True,
    )
