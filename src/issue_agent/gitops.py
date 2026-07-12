from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .errors import GitError


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class IsolatedWorktree:
    original_repo: Path
    path: Path
    branch: str
    temp_root: Path
    base_ref: str

    @classmethod
    def create(cls, repo: str | Path, *, base_ref: str = "HEAD") -> IsolatedWorktree:
        original = git_root(repo)
        temp_root = Path(tempfile.mkdtemp(prefix="gia-worktree-"))
        worktree_path = temp_root / "repo"
        branch = f"gia/{uuid.uuid4().hex[:12]}"
        run_git(["worktree", "add", "-b", branch, str(worktree_path), base_ref], cwd=original)
        return cls(
            original_repo=original,
            path=worktree_path,
            branch=branch,
            temp_root=temp_root,
            base_ref=base_ref,
        )

    def cleanup(self) -> None:
        with suppress(GitError):
            run_git(["worktree", "remove", "--force", str(self.path)], cwd=self.original_repo)
        with suppress(GitError):
            run_git(["branch", "-D", self.branch], cwd=self.original_repo)
        shutil.rmtree(self.temp_root, ignore_errors=True)


def run_git(
    args: list[str],
    *,
    cwd: str | Path,
    input_text: str | None = None,
    check: bool = True,
) -> GitResult:
    command = ["git", *args]
    result = subprocess.run(
        command,
        cwd=Path(cwd),
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    git_result = GitResult(
        args=tuple(command),
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if check and result.returncode != 0:
        raise GitError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return git_result


def git_root(path: str | Path) -> Path:
    repo_path = Path(path).expanduser().resolve()
    result = run_git(["rev-parse", "--show-toplevel"], cwd=repo_path, check=False)
    if result.returncode != 0:
        raise GitError(f"Not a git repository: {repo_path}")
    return Path(result.stdout.strip()).resolve()


def is_dirty(repo: str | Path) -> bool:
    result = run_git(["status", "--porcelain"], cwd=repo)
    return bool(result.stdout.strip())


def list_tracked_files(repo: str | Path, *, max_files: int | None = None) -> list[str]:
    result = run_git(["ls-files"], cwd=repo)
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    preferred = sorted(files, key=_file_rank)
    return preferred if max_files is None else preferred[:max_files]


def discover_context_files(
    repo: str | Path,
    issue_text: str,
    tracked_files: list[str],
    *,
    max_files: int = 400,
) -> list[str]:
    terms = _issue_search_terms(issue_text)
    path_ranked = sorted(tracked_files, key=lambda path: _context_file_rank(path, terms))
    content_matches = _git_grep_files(repo, terms)
    selected: list[str] = []
    seen: set[str] = set()
    tracked = set(tracked_files)
    for path in [*content_matches, *path_ranked]:
        if path in tracked and path not in seen:
            selected.append(path)
            seen.add(path)
        if len(selected) >= max_files:
            break
    return selected


def read_selected_files(
    repo: str | Path, files: list[str], *, max_total_chars: int = 120_000
) -> str:
    root = Path(repo)
    parts: list[str] = []
    used = 0
    for file_name in files:
        if used >= max_total_chars:
            break
        path = root / file_name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        remaining = max_total_chars - used
        snippet = text[:remaining]
        used += len(snippet)
        parts.append(f"--- {file_name} ---\n{snippet}")
    return "\n\n".join(parts)


def current_diff(repo: str | Path) -> str:
    return run_git(["diff", "--binary"], cwd=repo).stdout


def reset_worktree(repo: str | Path) -> None:
    run_git(["reset", "--hard", "HEAD"], cwd=repo)
    run_git(["clean", "-fd"], cwd=repo)


def _file_rank(path: str) -> tuple[int, int, int, str]:
    suffix_rank = 0 if path.endswith(".py") else 1
    test_rank = 1 if "/test" in path or path.startswith("test") else 0
    important_rank = 0 if Path(path).name in {"pyproject.toml", "setup.py", "setup.cfg"} else 1
    return (important_rank, suffix_rank, test_rank, path)


def _issue_search_terms(text: str, *, limit: int = 12) -> list[str]:
    ignored = {
        "and",
        "the",
        "for",
        "with",
        "from",
        "this",
        "that",
        "issue",
        "error",
        "when",
        "python",
        "추가",
        "수정",
        "오류",
        "문제",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}|[가-힣]{2,}", text):
        normalized = token.casefold().strip(".-")
        if not normalized or normalized in ignored or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
        if len(terms) >= limit:
            break
    return terms


def _context_file_rank(path: str, terms: list[str]) -> tuple[int, tuple[int, int, int, str]]:
    normalized = path.casefold()
    matches = sum(1 for term in terms if term in normalized)
    return (-matches, _file_rank(path))


def _git_grep_files(repo: str | Path, terms: list[str]) -> list[str]:
    if not terms:
        return []
    args = ["grep", "-Il", "-i"]
    for term in terms:
        args.extend(["-e", term])
    args.append("--")
    result = run_git(args, cwd=repo, check=False)
    if result.returncode not in {0, 1}:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
