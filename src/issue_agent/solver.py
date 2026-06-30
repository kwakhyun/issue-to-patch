from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .errors import GiaError, ModelError, PatchError
from .executor import CommandResult, CommandRunner, summarize_results
from .gitops import (
    IsolatedWorktree,
    current_diff,
    is_dirty,
    list_tracked_files,
    read_selected_files,
)
from .issue import Issue
from .patches import apply_unified_diff, check_unified_diff, extract_unified_diff
from .router import ModelRouter


@dataclass(frozen=True)
class AttemptRecord:
    iteration: int
    provider: str | None
    model: str | None
    patch_valid: bool
    patch_dry_run_passed: bool
    patch_applied: bool
    checks_passed: bool
    failure_stage: str | None
    error: str | None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    check_results: list[CommandResult] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "provider": self.provider,
            "model": self.model,
            "patch_valid": self.patch_valid,
            "patch_dry_run_passed": self.patch_dry_run_passed,
            "patch_applied": self.patch_applied,
            "checks_passed": self.checks_passed,
            "failure_stage": self.failure_stage,
            "error": self.error,
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "checks": [
                {
                    "command": result.command,
                    "returncode": result.returncode,
                    "passed": result.passed,
                    "duration_seconds": result.duration_seconds,
                    "sandbox": result.sandbox,
                }
                for result in self.check_results
            ],
        }


@dataclass(frozen=True)
class SolveResult:
    resolved: bool
    status: str
    diff: str
    metadata: dict[str, Any]
    attempts: list[AttemptRecord]


class IssueSolver:
    def __init__(
        self,
        *,
        config: Config,
        sandbox: str,
        model_profile: str | None,
        max_iters: int,
        allow_dirty: bool = False,
    ) -> None:
        if max_iters < 1:
            raise ValueError("max_iters must be >= 1")
        self.config = config
        self.sandbox = sandbox
        self.model_profile = model_profile
        self.max_iters = max_iters
        self.allow_dirty = allow_dirty

    def solve(self, *, repo: str | Path, issue: Issue, diff_only: bool = False) -> SolveResult:
        repo_path = Path(repo).expanduser().resolve()
        start = time.monotonic()
        original_dirty = is_dirty(repo_path)
        if original_dirty and not self.allow_dirty:
            raise GiaError(
                "Target repository has uncommitted changes; pass --allow-dirty to proceed"
            )
        worktree = IsolatedWorktree.create(repo_path)
        attempts: list[AttemptRecord] = []
        total_cost = 0.0
        final_diff = ""
        status = "failed"
        resolved = False
        try:
            router = ModelRouter(self.config, model_profile=self.model_profile)
            tracked_files = list_tracked_files(worktree.path)
            selected_files = router.choose_files(issue, tracked_files)
            if router.last_triage_response:
                total_cost += router.last_triage_response.cost_usd
            file_context = read_selected_files(worktree.path, selected_files)
            feedback: str | None = None
            runner = CommandRunner(
                sandbox=self.sandbox,
                sandbox_config=self.config.sandbox,
                timeout_seconds=self.config.checks.timeout_seconds,
            )

            for iteration in range(1, self.max_iters + 1):
                response = None
                patch_valid = False
                patch_dry_run_passed = False
                patch_applied = False
                checks_passed = False
                check_results: list[CommandResult] = []
                failure_stage: str | None = None
                error: str | None = None
                try:
                    failure_stage = "model"
                    response = router.generate_patch(
                        issue=issue,
                        file_context=file_context,
                        current_diff=current_diff(worktree.path),
                        feedback=feedback,
                    )
                    total_cost += response.cost_usd
                    failure_stage = "extract_patch"
                    patch = extract_unified_diff(response.text)
                    patch_valid = True
                    failure_stage = "patch_dry_run"
                    check_unified_diff(worktree.path, patch)
                    patch_dry_run_passed = True
                    if diff_only:
                        final_diff = patch
                        status = "diff_only"
                        attempts.append(
                            _attempt(
                                iteration=iteration,
                                response=response,
                                patch_valid=patch_valid,
                                patch_dry_run_passed=patch_dry_run_passed,
                                patch_applied=False,
                                checks_passed=False,
                                failure_stage=None,
                                error=None,
                                check_results=[],
                            )
                        )
                        break
                    failure_stage = "apply_patch"
                    apply_unified_diff(worktree.path, patch)
                    patch_applied = True
                    failure_stage = "checks"
                    check_results = runner.run_checks(
                        self.config.checks.enabled_commands(), worktree.path
                    )
                    checks_passed = all(result.passed for result in check_results)
                    final_diff = current_diff(worktree.path)
                    if checks_passed:
                        resolved = True
                        status = "resolved"
                        attempts.append(
                            _attempt(
                                iteration=iteration,
                                response=response,
                                patch_valid=patch_valid,
                                patch_dry_run_passed=patch_dry_run_passed,
                                patch_applied=patch_applied,
                                checks_passed=checks_passed,
                                failure_stage=None,
                                error=None,
                                check_results=check_results,
                            )
                        )
                        break
                    feedback = summarize_results(check_results)
                    error = "checks_failed"
                except (ModelError, PatchError, GiaError) as exc:
                    error = str(exc)
                    feedback = error
                    try:
                        final_diff = current_diff(worktree.path)
                    except GiaError:
                        final_diff = ""

                attempts.append(
                    _attempt(
                        iteration=iteration,
                        response=response,
                        patch_valid=patch_valid,
                        patch_dry_run_passed=patch_dry_run_passed,
                        patch_applied=patch_applied,
                        checks_passed=checks_passed,
                        failure_stage=failure_stage,
                        error=error,
                        check_results=check_results,
                    )
                )
            else:
                status = "max_iters_exhausted"

            if status == "failed" and attempts:
                status = "unresolved"

            metadata = {
                "repo": str(repo_path),
                "issue_source": issue.source,
                "issue_url": issue.url,
                "resolved": resolved,
                "status": status,
                "sandbox": self.sandbox,
                "model_profile": self.model_profile,
                "max_iters": self.max_iters,
                "allow_dirty": self.allow_dirty,
                "attempt_count": len(attempts),
                "cost_usd": total_cost,
                "triage": _model_response_metadata(router.last_triage_response),
                "duration_seconds": time.monotonic() - start,
                "original_dirty": original_dirty,
                "worktree_branch": worktree.branch,
                "selected_files": selected_files,
                "attempts": [attempt.to_json() for attempt in attempts],
            }
            return SolveResult(
                resolved=resolved,
                status=status,
                diff=final_diff,
                metadata=metadata,
                attempts=attempts,
            )
        finally:
            worktree.cleanup()


def append_metadata(path: str | Path, metadata: dict[str, Any]) -> None:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n")


def _attempt(
    *,
    iteration: int,
    response: Any,
    patch_valid: bool,
    patch_dry_run_passed: bool,
    patch_applied: bool,
    checks_passed: bool,
    failure_stage: str | None,
    error: str | None,
    check_results: list[CommandResult],
) -> AttemptRecord:
    return AttemptRecord(
        iteration=iteration,
        provider=getattr(response, "provider", None),
        model=getattr(response, "model", None),
        patch_valid=patch_valid,
        patch_dry_run_passed=patch_dry_run_passed,
        patch_applied=patch_applied,
        checks_passed=checks_passed,
        failure_stage=failure_stage,
        error=error,
        cost_usd=float(getattr(response, "cost_usd", 0.0)),
        input_tokens=int(getattr(response, "input_tokens", 0)),
        output_tokens=int(getattr(response, "output_tokens", 0)),
        check_results=check_results,
    )


def _model_response_metadata(response: Any) -> dict[str, Any] | None:
    if response is None:
        return None
    return {
        "provider": getattr(response, "provider", None),
        "model": getattr(response, "model", None),
        "cost_usd": float(getattr(response, "cost_usd", 0.0)),
        "input_tokens": int(getattr(response, "input_tokens", 0)),
        "output_tokens": int(getattr(response, "output_tokens", 0)),
    }
