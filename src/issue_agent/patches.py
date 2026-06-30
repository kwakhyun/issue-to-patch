from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import PatchError


def extract_unified_diff(text: str) -> str:
    candidate = text.strip()
    if not candidate:
        raise PatchError("Model returned an empty patch")
    if "```" in candidate:
        candidate = _strip_markdown_fences(candidate)

    lines = candidate.splitlines()
    start = _find_diff_start(lines)
    if start is None:
        raise PatchError("Model response did not contain a unified diff")
    diff = "\n".join(lines[start:]).strip()
    diff = re.sub(r"\n```$", "", diff).strip()
    return validate_unified_diff(diff)


def validate_unified_diff(diff: str) -> str:
    normalized = diff.strip()
    if not normalized:
        raise PatchError("Patch is empty")
    has_git_header = bool(re.search(r"^diff --git a/.+ b/.+", normalized, flags=re.MULTILINE))
    has_file_header = bool(re.search(r"^--- .+\n\+\+\+ .+\n@@ ", normalized, flags=re.MULTILINE))
    if not has_git_header and not has_file_header:
        raise PatchError("Patch must include git or unified diff file headers")
    if "@@" not in normalized:
        raise PatchError("Patch must include at least one hunk header")
    return normalized + "\n"


def check_unified_diff(repo: str | Path, diff: str) -> None:
    validate_unified_diff(diff)
    result = subprocess.run(
        ["git", "apply", "--check", "--whitespace=fix", "-"],
        cwd=Path(repo),
        input=diff,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise PatchError(f"git apply --check failed: {message}")


def apply_unified_diff(repo: str | Path, diff: str) -> None:
    check_unified_diff(repo, diff)
    result = subprocess.run(
        ["git", "apply", "--whitespace=fix", "-"],
        cwd=Path(repo),
        input=diff,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise PatchError(f"git apply failed after successful dry-run: {message}")


def _strip_markdown_fences(text: str) -> str:
    lines = text.strip().splitlines()
    fenced_blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.strip().startswith("```"):
            if current is None:
                current = []
            else:
                fenced_blocks.append(current)
                current = None
            continue
        if current is not None:
            current.append(line)
    for block in fenced_blocks:
        joined = "\n".join(block)
        if "diff --git" in joined or re.search(r"^--- .+\n\+\+\+ .+\n@@ ", joined, re.MULTILINE):
            return joined
    return text


def _find_diff_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith("diff --git "):
            return index
    for index, line in enumerate(lines[:-2]):
        if line.startswith("--- ") and lines[index + 1].startswith("+++ "):
            return index
    return None
