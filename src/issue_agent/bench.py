from __future__ import annotations

import json
import shlex
import subprocess
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import load_config
from .errors import GiaError
from .issue import load_issue
from .metrics import load_jsonl
from .solver import IssueSolver, SolveOptions

_REPO_LOCKS: dict[str, threading.Lock] = {}
_REPO_LOCKS_GUARD = threading.Lock()


def write_swebench_predictions(
    *,
    predictions_path: str | Path,
    dataset: str,
    limit: int | None,
    cases_path: str | Path | None = None,
    model_name: str = "gia-local",
) -> int:
    records = _load_cases(cases_path)
    if limit is not None:
        records = records[:limit]
    output_path = Path(predictions_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for index, record in enumerate(records):
            instance_id = str(record.get("instance_id") or record.get("id") or f"{dataset}-{index}")
            patch = str(
                record.get("model_patch")
                or record.get("prediction")
                or record.get("patch")
                or record.get("diff")
                or ""
            )
            prediction = {
                "instance_id": instance_id,
                "model_name_or_path": model_name,
                "model_patch": patch,
            }
            file.write(json.dumps(prediction, ensure_ascii=False, sort_keys=True) + "\n")
    return len(records)


def run_swebench_harness(
    *,
    command: str,
    predictions_path: str | Path,
    dataset: str,
    timeout_seconds: int = 7200,
) -> int:
    if timeout_seconds <= 0:
        raise GiaError("SWE-bench harness timeout must be positive")
    values = {
        "predictions": str(Path(predictions_path).expanduser().resolve()),
        "dataset": dataset,
    }
    try:
        args = [part.format(**values) for part in shlex.split(command)]
    except (KeyError, ValueError) as exc:
        raise GiaError(f"Invalid SWE-bench harness command template: {exc}") from exc
    if not args:
        raise GiaError("SWE-bench harness command cannot be empty")
    try:
        result = subprocess.run(args, text=True, check=False, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise GiaError(f"SWE-bench harness executable was not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GiaError(f"SWE-bench harness timed out after {timeout_seconds}s") from exc
    return result.returncode


def summarize_korean_benchmark(*, cases_path: str | Path, out_path: str | Path) -> int:
    cases = _load_cases(cases_path)
    output = Path(out_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for case in cases:
            issue_source = case.get("issue") or case.get("issue_text") or case.get("issue_file")
            record = {
                "id": case.get("id") or case.get("instance_id"),
                "repo": case.get("repo"),
                "issue_source": issue_source,
                "resolved": bool(case.get("resolved", False)),
                "status": case.get("status", "pending"),
                "cost_usd": float(case.get("cost_usd") or 0.0),
                "model_profile": case.get("model_profile") or case.get("model") or "default",
            }
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return len(cases)


def run_korean_benchmark(
    *,
    cases_path: str | Path,
    out_path: str | Path,
    limit: int | None = None,
    sandbox: str | None = None,
    config_path: str | Path | None = None,
    model_profile: str | None = None,
    max_iters: int = 3,
    allow_dirty: bool = False,
    skip_checks: bool = False,
    check_commands: tuple[str, ...] | None = None,
    resume: bool = False,
    workers: int = 1,
) -> int:
    if workers < 1:
        raise GiaError("benchmark workers must be >= 1")
    cases = _load_cases(cases_path)
    if limit is not None:
        cases = cases[:limit]
    output = Path(out_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = _completed_case_ids(output) if resume else set()
    pending = [
        (index, case) for index, case in enumerate(cases) if _case_id(case, index) not in completed
    ]

    def solve_case(item: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        index, case = item
        try:
            return _solve_korean_case(
                case=case,
                index=index,
                sandbox=sandbox,
                config_path=config_path,
                model_profile=model_profile,
                max_iters=max_iters,
                allow_dirty=allow_dirty,
                skip_checks=skip_checks,
                check_commands=check_commands,
            )
        except Exception as exc:  # noqa: BLE001 - one case must not abort a benchmark batch.
            return _korean_error_record(
                case_id=_case_id(case, index),
                repo=_optional_case_str(case.get("repo")),
                message=f"{exc.__class__.__name__}: {exc}",
            )

    mode = "a" if resume and output.exists() else "w"
    with output.open(mode, encoding="utf-8") as file:
        records: Iterable[dict[str, Any]]
        if workers == 1:
            records = map(solve_case, pending)
        else:
            executor = ThreadPoolExecutor(max_workers=workers)
            records = executor.map(solve_case, pending)
        try:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                file.flush()
        finally:
            if workers != 1:
                executor.shutdown(wait=True)
    return len(pending)


def _solve_korean_case(
    *,
    case: dict[str, Any],
    index: int,
    sandbox: str | None,
    config_path: str | Path | None,
    model_profile: str | None,
    max_iters: int,
    allow_dirty: bool,
    skip_checks: bool,
    check_commands: tuple[str, ...] | None,
) -> dict[str, Any]:
    case_id = _case_id(case, index)
    repo = case.get("repo")
    if not repo:
        return _korean_error_record(case_id=case_id, repo=None, message="case.repo is required")
    try:
        config = load_config(str(repo), config_path)
        issue = load_issue(
            issue_url=_optional_case_str(case.get("issue") or case.get("issue_url")),
            issue_file=_optional_case_str(case.get("issue_file")),
            issue_text=_optional_case_str(case.get("issue_text") or case.get("text")),
            repo=str(repo),
        )
        solver = IssueSolver(
            config=config,
            options=SolveOptions(
                sandbox=sandbox or config.sandbox.default,
                model_profile=model_profile,
                max_iters=max_iters,
                allow_dirty=allow_dirty,
                skip_checks=skip_checks,
                check_commands=check_commands,
            ),
        )
        with _repo_lock(str(repo)):
            result = solver.solve(repo=str(repo), issue=issue)
    except GiaError as exc:
        return _korean_error_record(case_id=case_id, repo=str(repo), message=str(exc))
    record = dict(result.metadata)
    record["benchmark"] = "korean"
    record["case_id"] = case_id
    return record


def _korean_error_record(*, case_id: str, repo: str | None, message: str) -> dict[str, Any]:
    return {
        "schema_version": "gia.bench.korean.v1",
        "benchmark": "korean",
        "case_id": case_id,
        "repo": repo,
        "resolved": False,
        "status": "error",
        "cost_usd": 0.0,
        "error": message,
    }


def _optional_case_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _case_id(case: dict[str, Any], index: int) -> str:
    return str(case.get("id") or case.get("instance_id") or f"korean-{index}")


def _completed_case_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        str(record.get("case_id"))
        for record in load_jsonl(path)
        if record.get("case_id") is not None
    }


def _repo_lock(repo: str) -> threading.Lock:
    key = str(Path(repo).expanduser().resolve())
    with _REPO_LOCKS_GUARD:
        return _REPO_LOCKS.setdefault(key, threading.Lock())


def _load_cases(cases_path: str | Path | None) -> list[dict[str, Any]]:
    if cases_path is None:
        return []
    path = Path(cases_path).expanduser().resolve()
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [record for record in data if isinstance(record, dict)]
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            return [record for record in data["cases"] if isinstance(record, dict)]
        return []
    return load_jsonl(path)
