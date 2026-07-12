from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .config import Config, validate_config
from .errors import GiaError, ModelError, PatchError
from .executor import CommandResult, CommandRunner, summarize_results
from .gitops import (
    IsolatedWorktree,
    current_diff,
    discover_context_files,
    is_dirty,
    list_tracked_files,
    read_selected_files,
    reset_worktree,
)
from .issue import Issue
from .patches import apply_unified_diff, check_unified_diff, extract_unified_diff
from .router import ModelRouter

KeepWorktree = Literal["never", "on-failure", "always"]
RepairStrategy = Literal["replacement", "incremental"]
SOLVE_METADATA_SCHEMA_VERSION = "gia.solve.v2"
ATTEMPT_OUTPUT_LIMIT = 64_000


@dataclass(frozen=True)
class SolveOptions:
    sandbox: str
    model_profile: str | None = None
    max_iters: int = 3
    diff_only: bool = False
    allow_dirty: bool = False
    base_ref: str = "HEAD"
    keep_worktree: KeepWorktree = "never"
    repair_strategy: RepairStrategy = "replacement"
    check_commands: tuple[str, ...] | None = None
    skip_checks: bool = False
    check_timeout_seconds: int | None = None
    context_max_files: int = 400
    context_max_chars: int = 120_000
    event_callback: Callable[[str], None] | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.max_iters < 1:
            raise GiaError("max-iters must be >= 1")
        if self.keep_worktree not in {"never", "on-failure", "always"}:
            raise GiaError("keep-worktree must be one of: never, on-failure, always")
        if self.repair_strategy not in {"replacement", "incremental"}:
            raise GiaError("repair-strategy must be one of: replacement, incremental")
        if self.check_timeout_seconds is not None and self.check_timeout_seconds <= 0:
            raise GiaError("check-timeout must be positive")
        if self.context_max_files <= 0:
            raise GiaError("context-max-files must be positive")
        if self.context_max_chars <= 0:
            raise GiaError("context-max-chars must be positive")


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

    def to_json(
        self,
        *,
        include_outputs: bool = False,
        output_limit: int = ATTEMPT_OUTPUT_LIMIT,
    ) -> dict[str, Any]:
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
                _command_result_to_json(
                    result,
                    include_outputs,
                    output_limit=output_limit,
                )
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
        options: SolveOptions,
    ) -> None:
        config_errors = [issue for issue in validate_config(config) if issue.severity == "error"]
        if config_errors:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in config_errors)
            raise GiaError(f"Invalid configuration: {details}")
        self.config = config
        self.options = options

    def solve(self, *, repo: str | Path, issue: Issue) -> SolveResult:
        repo_path = Path(repo).expanduser().resolve()
        start = time.monotonic()
        original_dirty = is_dirty(repo_path)
        if original_dirty and not self.options.allow_dirty:
            raise GiaError(
                "Target repository has uncommitted changes; pass --allow-dirty to proceed"
            )
        self._emit(f"creating worktree from {self.options.base_ref}")
        worktree = IsolatedWorktree.create(repo_path, base_ref=self.options.base_ref)
        self._emit(f"created worktree {worktree.path} on {worktree.branch}")
        attempts: list[AttemptRecord] = []
        total_cost = 0.0
        final_diff = ""
        status = "failed"
        resolved = False
        kept_worktree = _should_keep_worktree(self.options.keep_worktree, status, resolved)
        try:
            router = ModelRouter(self.config, model_profile=self.options.model_profile)
            self._emit("triaging repository files")
            tracked_files = list_tracked_files(worktree.path)
            context_candidates = discover_context_files(
                worktree.path,
                issue.prompt_text(),
                tracked_files,
                max_files=self.options.context_max_files,
            )
            selected_files = router.choose_files(issue, context_candidates)
            self._emit(f"selected {len(selected_files)} files for context")
            if router.last_triage_response:
                total_cost += router.last_triage_response.cost_usd
            file_context = read_selected_files(
                worktree.path,
                selected_files,
                max_total_chars=self.options.context_max_chars,
            )
            feedback: str | None = None
            check_commands = (
                self.options.check_commands
                if self.options.check_commands is not None
                else self.config.checks.enabled_commands()
            )
            runner = CommandRunner(
                sandbox=self.options.sandbox,
                sandbox_config=self.config.sandbox,
                timeout_seconds=(
                    self.options.check_timeout_seconds or self.config.checks.timeout_seconds
                ),
            )

            for iteration in range(1, self.options.max_iters + 1):
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
                    self._emit(f"iteration {iteration}: requesting patch")
                    response = router.generate_patch(
                        issue=issue,
                        file_context=file_context,
                        current_diff=current_diff(worktree.path),
                        feedback=feedback,
                        repair_strategy=self.options.repair_strategy,
                    )
                    total_cost += response.cost_usd
                    failure_stage = "extract_patch"
                    patch = extract_unified_diff(response.text)
                    patch_valid = True
                    previous_diff = current_diff(worktree.path)
                    if self.options.repair_strategy == "replacement":
                        self._emit(f"iteration {iteration}: replacing previous candidate")
                        reset_worktree(worktree.path)
                    failure_stage = "patch_dry_run"
                    self._emit(f"iteration {iteration}: dry-run checking patch")
                    try:
                        check_unified_diff(worktree.path, patch)
                    except PatchError:
                        _restore_candidate(worktree.path, previous_diff)
                        raise
                    patch_dry_run_passed = True
                    if self.options.diff_only:
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
                    self._emit(f"iteration {iteration}: applying patch")
                    try:
                        apply_unified_diff(worktree.path, patch)
                    except PatchError:
                        _restore_candidate(worktree.path, previous_diff)
                        raise
                    patch_applied = True
                    if self.options.skip_checks:
                        final_diff = current_diff(worktree.path)
                        status = "unchecked"
                        self._emit(f"iteration {iteration}: checks skipped")
                        attempts.append(
                            _attempt(
                                iteration=iteration,
                                response=response,
                                patch_valid=patch_valid,
                                patch_dry_run_passed=patch_dry_run_passed,
                                patch_applied=patch_applied,
                                checks_passed=False,
                                failure_stage=None,
                                error=None,
                                check_results=[],
                            )
                        )
                        break
                    failure_stage = "checks"
                    if not check_commands:
                        final_diff = current_diff(worktree.path)
                        status = "unchecked"
                        error = "no_checks_configured"
                        self._emit(f"iteration {iteration}: no checks configured")
                        attempts.append(
                            _attempt(
                                iteration=iteration,
                                response=response,
                                patch_valid=patch_valid,
                                patch_dry_run_passed=patch_dry_run_passed,
                                patch_applied=patch_applied,
                                checks_passed=False,
                                failure_stage=failure_stage,
                                error=error,
                                check_results=[],
                            )
                        )
                        break
                    self._emit(f"iteration {iteration}: running {len(check_commands)} checks")
                    check_results = runner.run_checks(check_commands, worktree.path)
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
                    self._emit(f"iteration {iteration}: checks failed")
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

            model_identity = _effective_model_identity(attempts)
            input_tokens = sum(attempt.input_tokens for attempt in attempts)
            output_tokens = sum(attempt.output_tokens for attempt in attempts)
            if router.last_triage_response:
                input_tokens += router.last_triage_response.input_tokens
                output_tokens += router.last_triage_response.output_tokens
            metadata = {
                "schema_version": SOLVE_METADATA_SCHEMA_VERSION,
                "run_id": self.options.run_id,
                "repo": str(repo_path),
                "issue_source": issue.source,
                "issue_url": issue.url,
                "resolved": resolved,
                "status": status,
                "sandbox": self.options.sandbox,
                "model_profile": model_identity["key"],
                "requested_model_profile": self.options.model_profile,
                "model_provider": model_identity["provider"],
                "model": model_identity["model"],
                "model_route": _model_route(attempts),
                "max_iters": self.options.max_iters,
                "allow_dirty": self.options.allow_dirty,
                "base_ref": self.options.base_ref,
                "keep_worktree": self.options.keep_worktree,
                "repair_strategy": self.options.repair_strategy,
                "kept_worktree": _should_keep_worktree(
                    self.options.keep_worktree, status, resolved
                ),
                "attempt_count": len(attempts),
                "cost_usd": total_cost,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "triage": _model_response_metadata(router.last_triage_response),
                "patch_provider": model_identity["provider"],
                "patch_provider_errors": router.last_patch_provider_errors,
                "patch_provider_error_history": router.patch_provider_error_history,
                "fallback_used": _fallback_used(self.config.router.fallback_model, attempts),
                "duration_seconds": time.monotonic() - start,
                "original_dirty": original_dirty,
                "worktree_path": str(worktree.path),
                "worktree_branch": worktree.branch,
                "selected_files": selected_files,
                "tracked_file_count": len(tracked_files),
                "context_candidate_count": len(context_candidates),
                "context_max_files": self.options.context_max_files,
                "context_max_chars": self.options.context_max_chars,
                "check_commands": list(check_commands),
                "checks_skipped": self.options.skip_checks,
                "check_timeout_seconds": (
                    self.options.check_timeout_seconds or self.config.checks.timeout_seconds
                ),
                "attempts": [attempt.to_json() for attempt in attempts],
            }
            kept_worktree = bool(metadata["kept_worktree"])
            return SolveResult(
                resolved=resolved,
                status=status,
                diff=final_diff,
                metadata=metadata,
                attempts=attempts,
            )
        finally:
            if not kept_worktree:
                worktree.cleanup()

    def _emit(self, message: str) -> None:
        if self.options.event_callback:
            self.options.event_callback(message)


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


def _command_result_to_json(
    result: CommandResult,
    include_outputs: bool,
    *,
    output_limit: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command": result.command,
        "returncode": result.returncode,
        "passed": result.passed,
        "duration_seconds": result.duration_seconds,
        "sandbox": result.sandbox,
    }
    if include_outputs:
        payload["stdout"] = _sanitize_output(result.stdout, limit=output_limit)
        payload["stderr"] = _sanitize_output(result.stderr, limit=output_limit)
    return payload


def _should_keep_worktree(policy: KeepWorktree, status: str, resolved: bool) -> bool:
    if policy == "always":
        return True
    if policy == "on-failure":
        return not resolved and status != "diff_only"
    return False


def _fallback_used(fallback_model: str | None, attempts: list[AttemptRecord]) -> bool:
    if not fallback_model:
        return False
    return any(attempt.provider == fallback_model for attempt in attempts)


def _effective_model_identity(attempts: list[AttemptRecord]) -> dict[str, str | None]:
    for attempt in reversed(attempts):
        if (attempt.patch_applied or attempt.patch_dry_run_passed) and (
            attempt.provider or attempt.model
        ):
            provider = attempt.provider
            model = attempt.model
            return {
                "provider": provider,
                "model": model,
                "key": _model_key(provider, model),
            }
    for attempt in reversed(attempts):
        if attempt.provider or attempt.model:
            return {
                "provider": attempt.provider,
                "model": attempt.model,
                "key": _model_key(attempt.provider, attempt.model),
            }
    return {"provider": None, "model": None, "key": "unknown"}


def _model_route(attempts: list[AttemptRecord]) -> list[dict[str, str | None]]:
    route: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for attempt in attempts:
        identity = (attempt.provider, attempt.model)
        if identity == (None, None) or identity in seen:
            continue
        seen.add(identity)
        route.append(
            {
                "provider": attempt.provider,
                "model": attempt.model,
                "key": _model_key(attempt.provider, attempt.model),
            }
        )
    return route


def _model_key(provider: str | None, model: str | None) -> str:
    if provider and model:
        return f"{provider}:{model}"
    return provider or model or "unknown"


def _restore_candidate(repo: str | Path, diff: str) -> None:
    reset_worktree(repo)
    if diff:
        apply_unified_diff(repo, diff)


def _sanitize_output(value: str, *, limit: int) -> str:
    redacted = _redact_secrets(value)
    if len(redacted) <= limit:
        return redacted
    omitted = len(redacted) - limit
    return redacted[:limit] + f"\n...[truncated {omitted} characters]"


def _redact_secrets(value: str) -> str:
    patterns = [
        r"(?i)(authorization:\s*bearer\s+)([A-Za-z0-9._~+/=-]+)",
        r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]{12,})",
        r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)([^\s'\";,]+)",
    ]
    redacted = value
    for pattern in patterns:
        redacted = re.sub(pattern, r"\1[REDACTED]", redacted)
    return redacted
