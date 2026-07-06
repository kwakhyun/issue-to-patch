from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import SandboxConfig


@dataclass(frozen=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    sandbox: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    def __init__(
        self,
        *,
        sandbox: str,
        sandbox_config: SandboxConfig,
        timeout_seconds: int,
    ) -> None:
        if sandbox not in {"local", "docker"}:
            raise ValueError("sandbox must be 'local' or 'docker'")
        self.sandbox = sandbox
        self.sandbox_config = sandbox_config
        self.timeout_seconds = timeout_seconds

    def run_checks(self, commands: tuple[str, ...], cwd: str | Path) -> list[CommandResult]:
        return [self.run(command, cwd) for command in commands]

    def run(self, command: str, cwd: str | Path) -> CommandResult:
        start = time.monotonic()
        if self.sandbox == "docker":
            result = self._run_docker(command, cwd)
        else:
            result = self._run_local(command, cwd)
        duration = time.monotonic() - start
        return CommandResult(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            sandbox=self.sandbox,
        )

    def _run_local(self, command: str, cwd: str | Path) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=Path(cwd),
                shell=True,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=command,
                returncode=124,
                stdout=_timeout_output(exc.stdout),
                stderr=_timeout_output(exc.stderr) + f"\nTimed out after {self.timeout_seconds}s",
            )

    def _run_docker(self, command: str, cwd: str | Path) -> subprocess.CompletedProcess[str]:
        if not shutil.which("docker"):
            return subprocess.CompletedProcess(
                args=["docker"],
                returncode=127,
                stdout="",
                stderr="docker executable was not found on PATH",
            )
        host_path = str(Path(cwd).resolve())
        volume = f"{host_path}:{self.sandbox_config.docker_workdir}"
        if self.sandbox_config.docker_read_only:
            volume += ":ro"
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.sandbox_config.docker_network,
            "-v",
            volume,
            "-w",
            self.sandbox_config.docker_workdir,
        ]
        if self.sandbox_config.docker_read_only:
            docker_command.append("--read-only")
        docker_user = _docker_user(self.sandbox_config.docker_user)
        if docker_user:
            docker_command.extend(["--user", docker_user])
        for name in self.sandbox_config.docker_env:
            if name in os.environ:
                docker_command.extend(["-e", name])
        docker_command.extend(
            [
                self.sandbox_config.docker_image,
                "sh",
                "-lc",
                command,
            ]
        )
        try:
            return subprocess.run(
                docker_command,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=docker_command,
                returncode=124,
                stdout=_timeout_output(exc.stdout),
                stderr=_timeout_output(exc.stderr) + f"\nTimed out after {self.timeout_seconds}s",
            )


def summarize_results(results: list[CommandResult]) -> str:
    if not results:
        return "No checks configured."
    parts: list[str] = []
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        parts.append(
            f"$ {result.command}\n"
            f"{status} exit={result.returncode} duration={result.duration_seconds:.2f}s\n"
            f"{output[:8000]}"
        )
    return "\n\n".join(parts)


def _timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _docker_user(configured: str | None) -> str | None:
    if configured:
        return configured
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        return f"{os.getuid()}:{os.getgid()}"
    return None
