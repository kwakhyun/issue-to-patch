from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from .errors import ConfigError


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    model: str
    role: str = "coder"
    api_key_env: str | None = None
    timeout_seconds: int = 120
    max_retries: int = 0
    retry_backoff_seconds: float = 1.0
    max_tokens: int | None = None
    input_cost_per_1m: float = 0.0
    output_cost_per_1m: float = 0.0


ConfigIssueSeverity = Literal["error", "warn"]


@dataclass(frozen=True)
class ConfigIssue:
    severity: ConfigIssueSeverity
    path: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"severity": self.severity, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class RouterConfig:
    triage_model: str = "triage"
    coder_model: str = "coder"
    fallback_model: str | None = None


@dataclass(frozen=True)
class ChecksConfig:
    commands: tuple[str, ...] = ("python -m pytest", "ruff check .")
    mypy_command: str = "mypy ."
    mypy_enabled: bool = False
    timeout_seconds: int = 600

    def enabled_commands(self) -> tuple[str, ...]:
        commands = list(self.commands)
        if self.mypy_enabled:
            commands.append(self.mypy_command)
        return tuple(commands)


@dataclass(frozen=True)
class SandboxConfig:
    default: str = "local"
    docker_image: str = "python:3.11"
    docker_workdir: str = "/workspace"
    docker_network: str = "none"
    docker_read_only: bool = False
    docker_env: tuple[str, ...] = ()
    docker_user: str | None = None
    docker_setup_commands: tuple[str, ...] = ()
    docker_tmpfs: tuple[str, ...] = ("/tmp",)


@dataclass(frozen=True)
class Config:
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    router: RouterConfig = field(default_factory=RouterConfig)
    checks: ChecksConfig = field(default_factory=ChecksConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)

    def provider(self, name: str | None) -> ProviderConfig | None:
        if not name:
            return None
        return self.providers.get(name)


LOCAL_CONFIG = """providers:
  triage:
    base_url: http://localhost:11434/v1
    model: qwen3:4b
    role: triage
    timeout_seconds: 60
    max_retries: 1
    max_tokens: 1500
  coder:
    base_url: http://localhost:8000/v1
    model: Qwen/Qwen3-Coder-30B-A3B-Instruct
    role: coder
    timeout_seconds: 120
    max_retries: 1
    max_tokens: 12000
  # Optional external fallback. Uncomment and set api_key_env only when you
  # explicitly want network fallback outside your local models.
  # fallback:
  #   base_url: https://api.example.com/v1
  #   api_key_env: EXTERNAL_API_KEY
  #   model: fallback-coder
  #   role: fallback
router:
  triage_model: triage
  coder_model: coder
  fallback_model: null
checks:
  commands:
    - python -m pytest
    - ruff check .
  mypy_enabled: false
  timeout_seconds: 600
sandbox:
  default: local
  docker_image: python:3.11
  docker_workdir: /workspace
  docker_network: none
  docker_read_only: false
  docker_env: []
  docker_user: null
  docker_setup_commands: []
  docker_tmpfs: [/tmp]
"""

OLLAMA_CONFIG = """providers:
  triage:
    base_url: http://localhost:11434/v1
    model: qwen3:4b
    role: triage
    timeout_seconds: 60
    max_retries: 1
    max_tokens: 1500
  coder:
    base_url: http://localhost:11434/v1
    model: qwen3-coder:latest
    role: coder
    timeout_seconds: 120
    max_retries: 1
    max_tokens: 12000
router:
  triage_model: triage
  coder_model: coder
  fallback_model: null
checks:
  commands:
    - python -m pytest
    - ruff check .
  mypy_enabled: false
  timeout_seconds: 600
sandbox:
  default: local
  docker_image: python:3.11
  docker_workdir: /workspace
  docker_network: none
  docker_read_only: false
  docker_env: []
  docker_user: null
  docker_setup_commands: []
  docker_tmpfs: [/tmp]
"""

VLLM_CONFIG = """providers:
  triage:
    base_url: http://localhost:8000/v1
    model: Qwen/Qwen3-4B-Instruct
    role: triage
    timeout_seconds: 60
    max_retries: 1
    max_tokens: 1500
  coder:
    base_url: http://localhost:8000/v1
    model: Qwen/Qwen3-Coder-30B-A3B-Instruct
    role: coder
    timeout_seconds: 120
    max_retries: 1
    max_tokens: 12000
router:
  triage_model: triage
  coder_model: coder
  fallback_model: null
checks:
  commands:
    - python -m pytest
    - ruff check .
  mypy_enabled: false
  timeout_seconds: 600
sandbox:
  default: local
  docker_image: python:3.11
  docker_workdir: /workspace
  docker_network: none
  docker_read_only: false
  docker_env: []
  docker_user: null
  docker_setup_commands: []
  docker_tmpfs: [/tmp]
"""

OPENAI_COMPATIBLE_CONFIG = """providers:
  coder:
    base_url: https://api.example.com/v1
    api_key_env: OPENAI_COMPATIBLE_API_KEY
    model: your-coder-model
    role: coder
    timeout_seconds: 120
    max_retries: 2
    retry_backoff_seconds: 1.5
    max_tokens: 12000
router:
  triage_model: coder
  coder_model: coder
  fallback_model: null
checks:
  commands:
    - python -m pytest
    - ruff check .
  mypy_enabled: false
  timeout_seconds: 600
sandbox:
  default: local
  docker_image: python:3.11
  docker_workdir: /workspace
  docker_network: none
  docker_read_only: false
  docker_env: []
  docker_user: null
  docker_setup_commands: []
  docker_tmpfs: [/tmp]
"""

CONFIG_PRESETS = {
    "local": LOCAL_CONFIG,
    "ollama": OLLAMA_CONFIG,
    "vllm": VLLM_CONFIG,
    "openai-compatible": OPENAI_COMPATIBLE_CONFIG,
}


def default_config() -> Config:
    return Config(
        providers={
            "triage": ProviderConfig(
                name="triage",
                base_url="http://localhost:11434/v1",
                model="qwen3:4b",
                role="triage",
            ),
            "coder": ProviderConfig(
                name="coder",
                base_url="http://localhost:8000/v1",
                model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
                role="coder",
            ),
        }
    )


def load_config(repo: str | Path, explicit_path: str | Path | None = None) -> Config:
    repo_path = Path(repo).expanduser().resolve()
    config_path = (
        Path(explicit_path).expanduser().resolve() if explicit_path else repo_path / ".gia.yaml"
    )
    base = default_config()
    if not config_path.exists():
        return base
    loaded = _load_yaml_mapping(config_path)
    return config_from_mapping(loaded, base)


def config_from_mapping(data: dict[str, Any], base: Config | None = None) -> Config:
    config = base or default_config()
    providers = dict(config.providers)
    for name, raw_provider in _as_mapping(data.get("providers", {}), "providers").items():
        if not isinstance(raw_provider, dict):
            raise ConfigError(f"providers.{name} must be a mapping")
        existing = providers.get(name)
        providers[name] = _provider_from_mapping(name, raw_provider, existing)

    router = config.router
    if "router" in data:
        raw_router = _as_mapping(data["router"], "router")
        router = replace(
            router,
            triage_model=str(raw_router.get("triage_model", router.triage_model)),
            coder_model=str(raw_router.get("coder_model", router.coder_model)),
            fallback_model=_optional_str(raw_router.get("fallback_model", router.fallback_model)),
        )

    checks = config.checks
    if "checks" in data:
        raw_checks = _as_mapping(data["checks"], "checks")
        commands = raw_checks.get("commands", checks.commands)
        commands_tuple: tuple[str, ...]
        if isinstance(commands, str):
            commands_tuple = (commands,)
        elif isinstance(commands, list | tuple):
            commands_tuple = tuple(str(command) for command in commands)
        else:
            raise ConfigError("checks.commands must be a string or list of strings")
        checks = replace(
            checks,
            commands=commands_tuple,
            mypy_command=str(raw_checks.get("mypy_command", checks.mypy_command)),
            mypy_enabled=_as_bool(raw_checks.get("mypy_enabled", checks.mypy_enabled)),
            timeout_seconds=int(raw_checks.get("timeout_seconds", checks.timeout_seconds)),
        )

    sandbox = config.sandbox
    if "sandbox" in data:
        raw_sandbox = _as_mapping(data["sandbox"], "sandbox")
        docker_env = raw_sandbox.get("docker_env", sandbox.docker_env)
        docker_env_tuple: tuple[str, ...]
        if isinstance(docker_env, str):
            docker_env_tuple = (docker_env,)
        elif isinstance(docker_env, list | tuple):
            docker_env_tuple = tuple(str(item) for item in docker_env)
        else:
            raise ConfigError("sandbox.docker_env must be a string or list of strings")
        docker_setup_commands = _string_tuple(
            raw_sandbox.get("docker_setup_commands", sandbox.docker_setup_commands),
            "sandbox.docker_setup_commands",
        )
        docker_tmpfs = _string_tuple(
            raw_sandbox.get("docker_tmpfs", sandbox.docker_tmpfs),
            "sandbox.docker_tmpfs",
        )
        sandbox = replace(
            sandbox,
            default=str(raw_sandbox.get("default", sandbox.default)),
            docker_image=str(raw_sandbox.get("docker_image", sandbox.docker_image)),
            docker_workdir=str(raw_sandbox.get("docker_workdir", sandbox.docker_workdir)),
            docker_network=str(raw_sandbox.get("docker_network", sandbox.docker_network)),
            docker_read_only=_as_bool(
                raw_sandbox.get("docker_read_only", sandbox.docker_read_only)
            ),
            docker_env=docker_env_tuple,
            docker_user=_optional_str(raw_sandbox.get("docker_user", sandbox.docker_user)),
            docker_setup_commands=docker_setup_commands,
            docker_tmpfs=docker_tmpfs,
        )
        if sandbox.default not in {"local", "docker"}:
            raise ConfigError("sandbox.default must be 'local' or 'docker'")

    return Config(providers=providers, router=router, checks=checks, sandbox=sandbox)


def available_config_presets() -> tuple[str, ...]:
    return tuple(CONFIG_PRESETS)


def sample_config_text(preset: str = "local") -> str:
    try:
        return CONFIG_PRESETS[preset]
    except KeyError as exc:
        options = ", ".join(available_config_presets())
        raise ConfigError(
            f"Unknown config preset '{preset}'. Available presets: {options}"
        ) from exc


def validate_config(config: Config) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    provider_names = set(config.providers)

    for router_field, provider_name in [
        ("triage_model", config.router.triage_model),
        ("coder_model", config.router.coder_model),
    ]:
        if provider_name not in provider_names:
            issues.append(
                ConfigIssue(
                    "error",
                    f"router.{router_field}",
                    f"provider '{provider_name}' is not defined",
                )
            )

    if config.router.fallback_model and config.router.fallback_model not in provider_names:
        issues.append(
            ConfigIssue(
                "error",
                "router.fallback_model",
                f"provider '{config.router.fallback_model}' is not defined",
            )
        )

    for name, provider in sorted(config.providers.items()):
        if not provider.base_url:
            issues.append(
                ConfigIssue("error", f"providers.{name}.base_url", "base_url is required")
            )
        if not provider.model:
            issues.append(ConfigIssue("error", f"providers.{name}.model", "model is required"))
        if provider.timeout_seconds <= 0:
            issues.append(
                ConfigIssue(
                    "error",
                    f"providers.{name}.timeout_seconds",
                    "timeout must be positive",
                )
            )
        if provider.max_retries < 0:
            issues.append(
                ConfigIssue(
                    "error",
                    f"providers.{name}.max_retries",
                    "max_retries must be non-negative",
                )
            )
        if provider.retry_backoff_seconds < 0:
            issues.append(
                ConfigIssue(
                    "error",
                    f"providers.{name}.retry_backoff_seconds",
                    "retry backoff must be non-negative",
                )
            )
        if provider.max_tokens is not None and provider.max_tokens <= 0:
            issues.append(
                ConfigIssue(
                    "error",
                    f"providers.{name}.max_tokens",
                    "max_tokens must be positive when set",
                )
            )
        if provider.input_cost_per_1m < 0:
            issues.append(
                ConfigIssue(
                    "error",
                    f"providers.{name}.input_cost_per_1m",
                    "cost must be non-negative",
                )
            )
        if provider.output_cost_per_1m < 0:
            issues.append(
                ConfigIssue(
                    "error",
                    f"providers.{name}.output_cost_per_1m",
                    "cost must be non-negative",
                )
            )

    if not config.checks.commands:
        issues.append(ConfigIssue("warn", "checks.commands", "no validation commands configured"))
    if config.checks.timeout_seconds <= 0:
        issues.append(ConfigIssue("error", "checks.timeout_seconds", "timeout must be positive"))
    if config.sandbox.default not in {"local", "docker"}:
        issues.append(ConfigIssue("error", "sandbox.default", "must be 'local' or 'docker'"))
    if not config.sandbox.docker_image:
        issues.append(ConfigIssue("warn", "sandbox.docker_image", "docker sandbox has no image"))
    if not config.sandbox.docker_workdir.startswith("/"):
        issues.append(ConfigIssue("error", "sandbox.docker_workdir", "must be an absolute path"))
    if config.sandbox.docker_network == "":
        issues.append(ConfigIssue("warn", "sandbox.docker_network", "docker network is empty"))
    for index, name in enumerate(config.sandbox.docker_env):
        if not name:
            issues.append(ConfigIssue("error", f"sandbox.docker_env.{index}", "env name is empty"))
    for index, command in enumerate(config.sandbox.docker_setup_commands):
        if not command.strip():
            issues.append(
                ConfigIssue("error", f"sandbox.docker_setup_commands.{index}", "command is empty")
            )
    for index, mount in enumerate(config.sandbox.docker_tmpfs):
        if not mount.startswith("/"):
            issues.append(
                ConfigIssue("error", f"sandbox.docker_tmpfs.{index}", "must be an absolute path")
            )

    return issues


def _provider_from_mapping(
    name: str, data: dict[str, Any], existing: ProviderConfig | None
) -> ProviderConfig:
    base = existing or ProviderConfig(name=name, base_url="", model="")
    return replace(
        base,
        name=name,
        base_url=str(data.get("base_url", base.base_url)),
        model=str(data.get("model", base.model)),
        role=str(data.get("role", base.role)),
        api_key_env=_optional_str(data.get("api_key_env", base.api_key_env)),
        timeout_seconds=int(data.get("timeout_seconds", base.timeout_seconds)),
        max_retries=int(data.get("max_retries", base.max_retries)),
        retry_backoff_seconds=float(data.get("retry_backoff_seconds", base.retry_backoff_seconds)),
        max_tokens=_optional_int(data.get("max_tokens", base.max_tokens)),
        input_cost_per_1m=float(data.get("input_cost_per_1m", base.input_cost_per_1m)),
        output_cost_per_1m=float(data.get("output_cost_per_1m", base.output_cost_per_1m)),
    )


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        data = _parse_simple_yaml(text)
    else:
        loaded = yaml.safe_load(text)
        data = loaded or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return data


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, stripped))
    if not lines:
        return {}

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
            items: list[Any] = []
            while index < len(lines):
                current_indent, stripped_line = lines[index]
                if current_indent < indent:
                    break
                if current_indent != indent or not stripped_line.startswith("- "):
                    break
                items.append(_parse_scalar(stripped_line[2:].strip()))
                index += 1
            return items, index

        mapping: dict[str, Any] = {}
        while index < len(lines):
            current_indent, stripped_line = lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ConfigError(f"Unexpected indentation near: {stripped_line}")
            if ":" not in stripped_line:
                raise ConfigError(f"Expected 'key: value' near: {stripped_line}")
            key, raw_value = stripped_line.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            if not key:
                raise ConfigError("YAML key cannot be empty")
            index += 1
            if raw_value:
                mapping[key] = _parse_scalar(raw_value)
            else:
                value, index = parse_block(index, indent + 2)
                mapping[key] = value
        return mapping, index

    parsed, end_index = parse_block(0, lines[0][0])
    if end_index != len(lines):
        raise ConfigError("Could not parse entire YAML document")
    if not isinstance(parsed, dict):
        raise ConfigError("Config YAML must be a mapping")
    return parsed


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in {"1", "true", "yes", "on"}:
            return True
        if value.lower() in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    raise ConfigError(f"{name} must be a string or list of strings")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
