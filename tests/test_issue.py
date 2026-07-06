import json
import subprocess

import pytest

from issue_agent.errors import IssueLoadError
from issue_agent.issue import (
    is_github_issue_url,
    load_issue,
    load_issue_file,
    resolve_github_issue_ref,
)


def test_issue_text_uses_first_line_as_title():
    issue = load_issue(issue_text="Fix parser\n\nParser fails on comments")

    assert issue.title == "Fix parser"
    assert "comments" in issue.body


def test_issue_json_file(tmp_path):
    path = tmp_path / "issue.json"
    path.write_text(json.dumps({"title": "Bug", "body": "It breaks", "url": "u"}), encoding="utf-8")

    issue = load_issue_file(path)

    assert issue.title == "Bug"
    assert issue.body == "It breaks"
    assert issue.url == "u"


def test_github_issue_url_validation():
    assert is_github_issue_url("https://github.com/owner/repo/issues/123")
    assert not is_github_issue_url("https://github.com/owner/repo/pull/123")


def test_resolve_owner_repo_issue_shorthand():
    assert resolve_github_issue_ref("owner/repo#123") == "https://github.com/owner/repo/issues/123"


def test_resolve_local_issue_shorthand_from_origin(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    assert (
        resolve_github_issue_ref("#123", repo=tmp_path)
        == "https://github.com/owner/repo/issues/123"
    )


def test_resolve_local_issue_shorthand_requires_github_origin(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    with pytest.raises(IssueLoadError, match="owner/repo#123"):
        resolve_github_issue_ref("#123", repo=tmp_path)


def test_fetch_github_issue_uses_gh(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["gh", "issue", "view"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"title": "Bug", "body": "Broken", "url": cmd[3]}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    issue = load_issue(issue_url="https://github.com/owner/repo/issues/123")

    assert issue.title == "Bug"
    assert issue.body == "Broken"


def test_fetch_github_issue_accepts_owner_repo_shorthand(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[3] == "https://github.com/owner/repo/issues/123"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"title": "Bug", "body": "Broken", "url": cmd[3]}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    issue = load_issue(issue_url="owner/repo#123")

    assert issue.url == "https://github.com/owner/repo/issues/123"


def test_load_issue_requires_one_source():
    with pytest.raises(IssueLoadError):
        load_issue(issue_text="x", issue_file="y")
