import json
import subprocess
import urllib.request

from issue_agent.cli import main
from issue_agent.diagnostics import format_doctor_report, run_doctor


def test_run_doctor_reports_tools_without_optional_failures(monkeypatch):
    def fake_which(name):
        return "/usr/bin/git" if name == "git" else None

    monkeypatch.setattr("issue_agent.diagnostics.shutil.which", fake_which)

    report = run_doctor()

    assert report.ok
    assert any(check.name == "git" and check.status == "pass" for check in report.checks)
    assert any(check.name == "docker" and check.status == "warn" for check in report.checks)
    assert "gia doctor: ok" in format_doctor_report(report)


def test_doctor_repo_json(tmp_path, capsys):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    code = main(["doctor", "--repo", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert code == 0
    assert data["ok"] is True
    assert any(check["name"] == "repo" for check in data["checks"])


def test_doctor_skips_config_when_repo_missing(tmp_path):
    report = run_doctor(repo=tmp_path / "missing")

    assert not report.ok
    assert any(check.name == "repo" and check.status == "fail" for check in report.checks)
    assert any(check.name == "config" and check.status == "skip" for check in report.checks)


class FakeHTTPResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_doctor_model_probe(monkeypatch, tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        assert request.full_url.endswith("/models")
        assert timeout == 5
        return FakeHTTPResponse()

    monkeypatch.setattr("issue_agent.diagnostics.urllib.request.urlopen", fake_urlopen)

    report = run_doctor(repo=tmp_path, probe_models=True)

    assert report.ok
    assert any(check.name == "model:coder" and check.status == "pass" for check in report.checks)
