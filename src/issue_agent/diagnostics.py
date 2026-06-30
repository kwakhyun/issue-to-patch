from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import Config, load_config, validate_config

DiagnosticStatus = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: DiagnosticStatus
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    checks: list[DiagnosticCheck]

    def to_json(self) -> dict[str, object]:
        return {"ok": self.ok, "checks": [check.to_json() for check in self.checks]}


def run_doctor(
    *,
    repo: str | Path | None = None,
    config_path: str | Path | None = None,
    check_gh_auth: bool = False,
    probe_models: bool = False,
) -> DoctorReport:
    checks: list[DiagnosticCheck] = []
    checks.append(_python_check())
    checks.extend(_tool_checks(check_gh_auth=check_gh_auth))

    config: Config | None = None
    repo_path = Path(repo).expanduser().resolve() if repo else None
    if repo_path is not None:
        repo_check = _repo_check(repo_path)
        checks.append(repo_check)
        if repo_check.status == "fail":
            checks.append(
                DiagnosticCheck("config", "skip", "repo check failed; config was not loaded")
            )
        else:
            try:
                config = load_config(repo_path, config_path)
            except Exception as exc:  # noqa: BLE001 - doctor should report config failures.
                checks.append(DiagnosticCheck("config", "fail", str(exc)))
            else:
                checks.append(_config_check(config, config_path or repo_path / ".gia.yaml"))
    elif config_path is not None:
        try:
            config = load_config(Path.cwd(), config_path)
        except Exception as exc:  # noqa: BLE001
            checks.append(DiagnosticCheck("config", "fail", str(exc)))
        else:
            checks.append(_config_check(config, config_path))

    if config is not None:
        checks.extend(_config_validation_checks(config))
        checks.extend(_provider_secret_checks(config))
        checks.append(_checks_config_check(config))
        if probe_models:
            checks.extend(_model_probe_checks(config))
    elif probe_models:
        checks.append(DiagnosticCheck("models", "skip", "config was not loaded"))

    ok = all(check.status != "fail" for check in checks)
    return DoctorReport(ok=ok, checks=checks)


def format_doctor_report(report: DoctorReport) -> str:
    lines = ["gia doctor: ok" if report.ok else "gia doctor: issues found"]
    for check in report.checks:
        lines.append(f"[{check.status.upper()}] {check.name}: {check.detail}")
    return "\n".join(lines)


def _python_check() -> DiagnosticCheck:
    version = sys.version_info
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if version < (3, 11):
        return DiagnosticCheck("python", "fail", f"{detail}; Python 3.11+ is required")
    return DiagnosticCheck("python", "pass", detail)


def _tool_checks(*, check_gh_auth: bool) -> list[DiagnosticCheck]:
    checks = [
        _which_check("git", required=True),
        _which_check("gh", required=False),
        _which_check("docker", required=False),
        _which_check("ruff", required=False),
        _which_check("mypy", required=False),
    ]
    if check_gh_auth:
        checks.append(_gh_auth_check())
    return checks


def _which_check(name: str, *, required: bool) -> DiagnosticCheck:
    path = _find_tool(name)
    if path:
        return DiagnosticCheck(name, "pass", path)
    status: DiagnosticStatus = "fail" if required else "warn"
    requirement = "required" if required else "optional"
    return DiagnosticCheck(name, status, f"{requirement} tool not found on PATH")


def _find_tool(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    sibling = Path(sys.executable).with_name(name)
    if sibling.exists() and sibling.is_file():
        return str(sibling)
    return None


def _repo_check(repo_path: Path) -> DiagnosticCheck:
    if not repo_path.exists():
        return DiagnosticCheck("repo", "fail", f"{repo_path} does not exist")
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=repo_path,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "not a git repository"
        return DiagnosticCheck("repo", "fail", detail)
    return DiagnosticCheck("repo", "pass", result.stdout.strip())


def _config_check(config: Config, path: str | Path) -> DiagnosticCheck:
    provider_count = len(config.providers)
    configured_path = Path(path).expanduser()
    if configured_path.exists():
        detail = f"loaded {provider_count} providers from {configured_path}"
    else:
        detail = f"using defaults with {provider_count} providers; no config file found"
    return DiagnosticCheck("config", "pass", detail)


def _provider_secret_checks(config: Config) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    for name, provider in sorted(config.providers.items()):
        if not provider.api_key_env:
            checks.append(DiagnosticCheck(f"provider:{name}", "pass", "no API key env required"))
            continue
        if os.environ.get(provider.api_key_env):
            checks.append(
                DiagnosticCheck(f"provider:{name}", "pass", f"{provider.api_key_env} is set")
            )
        else:
            checks.append(
                DiagnosticCheck(
                    f"provider:{name}",
                    "warn",
                    f"{provider.api_key_env} is not set; fallback calls may fail",
                )
            )
    return checks


def _config_validation_checks(config: Config) -> list[DiagnosticCheck]:
    issues = validate_config(config)
    if not issues:
        return [DiagnosticCheck("config-validate", "pass", "configuration is valid")]
    checks: list[DiagnosticCheck] = []
    for issue in issues:
        checks.append(
            DiagnosticCheck(
                f"config:{issue.path}",
                "fail" if issue.severity == "error" else "warn",
                issue.message,
            )
        )
    return checks


def _checks_config_check(config: Config) -> DiagnosticCheck:
    commands = config.checks.enabled_commands()
    if not commands:
        return DiagnosticCheck("checks", "warn", "no validation commands configured")
    return DiagnosticCheck("checks", "pass", "; ".join(commands))


def _model_probe_checks(config: Config) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    for name, provider in sorted(config.providers.items()):
        if provider.api_key_env and not os.environ.get(provider.api_key_env):
            checks.append(
                DiagnosticCheck(
                    f"model:{name}",
                    "skip",
                    f"{provider.api_key_env} is not set",
                )
            )
            continue
        request = urllib.request.Request(
            f"{provider.base_url.rstrip('/')}/models",
            headers=_provider_headers(provider.api_key_env),
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=min(provider.timeout_seconds, 10)
            ) as response:
                status = getattr(response, "status", 200)
        except urllib.error.URLError as exc:
            checks.append(DiagnosticCheck(f"model:{name}", "warn", f"probe failed: {exc}"))
        else:
            checks.append(DiagnosticCheck(f"model:{name}", "pass", f"GET /models -> {status}"))
    return checks


def _provider_headers(api_key_env: str | None) -> dict[str, str]:
    if not api_key_env:
        return {}
    api_key = os.environ.get(api_key_env)
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _gh_auth_check() -> DiagnosticCheck:
    if not shutil.which("gh"):
        return DiagnosticCheck("gh-auth", "warn", "gh is not installed")
    result = subprocess.run(
        ["gh", "auth", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return DiagnosticCheck("gh-auth", "pass", "authenticated")
    detail = result.stderr.strip() or result.stdout.strip() or "not authenticated"
    return DiagnosticCheck("gh-auth", "warn", detail)
