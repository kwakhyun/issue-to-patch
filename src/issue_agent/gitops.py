from __future__ import annotations

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


def list_tracked_files(repo: str | Path, *, max_files: int = 300) -> list[str]:
    result = run_git(["ls-files"], cwd=repo)
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    preferred = sorted(files, key=_file_rank)
    return preferred[:max_files]


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


def _file_rank(path: str) -> tuple[int, int, int, str]:
    suffix_rank = 0 if path.endswith(".py") else 1
    test_rank = 1 if "/test" in path or path.startswith("test") else 0
    important_rank = 0 if Path(path).name in {"pyproject.toml", "setup.py", "setup.cfg"} else 1
    return (important_rank, suffix_rank, test_rank, path)
