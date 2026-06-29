from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import IssueLoadError

GITHUB_ISSUE_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues/\d+(?:[?#].*)?$")


@dataclass(frozen=True)
class Issue:
    title: str
    body: str
    source: str
    url: str | None = None
    raw: dict[str, object] | None = None

    def prompt_text(self) -> str:
        if self.title and self.title != self.body:
            return f"# {self.title}\n\n{self.body}".strip()
        return self.body.strip()


def load_issue(
    *,
    issue_url: str | None = None,
    issue_file: str | Path | None = None,
    issue_text: str | None = None,
) -> Issue:
    provided = [value is not None for value in (issue_url, issue_file, issue_text)].count(True)
    if provided != 1:
        raise IssueLoadError("Provide exactly one of --issue, --issue-file, or --issue-text")
    if issue_url:
        if not is_github_issue_url(issue_url):
            raise IssueLoadError("Only GitHub issue URLs are supported for --issue")
        return fetch_github_issue(issue_url)
    if issue_file:
        return load_issue_file(issue_file)
    assert issue_text is not None
    return issue_from_text(issue_text, source="inline")


def is_github_issue_url(value: str) -> bool:
    return bool(GITHUB_ISSUE_RE.match(value.strip()))


def issue_from_text(text: str, *, source: str) -> Issue:
    body = text.strip()
    if not body:
        raise IssueLoadError("Issue text is empty")
    first_line = body.splitlines()[0].strip()
    title = first_line.lstrip("# ").strip() or "Untitled issue"
    return Issue(title=title, body=body, source=source)


def load_issue_file(path: str | Path) -> Issue:
    issue_path = Path(path).expanduser().resolve()
    if not issue_path.exists():
        raise IssueLoadError(f"Issue file does not exist: {issue_path}")
    text = issue_path.read_text(encoding="utf-8")
    if issue_path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise IssueLoadError(f"Could not parse issue JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise IssueLoadError("Issue JSON must be an object")
        title = str(data.get("title") or data.get("name") or "Untitled issue")
        body = str(data.get("body") or data.get("description") or data.get("text") or "")
        if not body.strip():
            raise IssueLoadError("Issue JSON must include body, description, or text")
        url = data.get("url")
        return Issue(
            title=title,
            body=body.strip(),
            source=str(issue_path),
            url=str(url) if url else None,
            raw=data,
        )
    return issue_from_text(text, source=str(issue_path))


def fetch_github_issue(url: str) -> Issue:
    cmd = ["gh", "issue", "view", url, "--json", "title,body,url,number,state,labels"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    except FileNotFoundError as exc:
        raise IssueLoadError(
            "GitHub issue URLs require the GitHub CLI (`gh`). "
            "Install/authenticate `gh`, or pass --issue-file with saved issue text."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise IssueLoadError("Timed out while fetching GitHub issue with `gh issue view`") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise IssueLoadError(
            "Could not fetch GitHub issue with `gh issue view`. "
            f"Pass --issue-file instead. gh said: {message}"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise IssueLoadError(f"`gh issue view` did not return valid JSON: {exc}") from exc
    title = str(data.get("title") or f"Issue {data.get('number', '')}").strip()
    body = str(data.get("body") or "").strip()
    if not body:
        raise IssueLoadError("Fetched GitHub issue has an empty body")
    return Issue(title=title, body=body, source=url, url=str(data.get("url") or url), raw=data)
