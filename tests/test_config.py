from issue_agent.config import (
    available_config_presets,
    config_from_mapping,
    load_config,
    sample_config_text,
    validate_config,
)


def test_load_config_defaults(tmp_path):
    config = load_config(tmp_path)

    assert config.router.triage_model == "triage"
    assert config.sandbox.default == "local"
    assert "python -m pytest" in config.checks.commands


def test_config_from_mapping_overrides_nested_values():
    config = config_from_mapping(
        {
            "providers": {
                "coder": {
                    "base_url": "http://localhost:9999/v1",
                    "model": "kimi-coder",
                    "timeout_seconds": 33,
                    "max_retries": 2,
                    "retry_backoff_seconds": 0.25,
                    "max_tokens": 4096,
                    "input_cost_per_1m": 1.0,
                },
                "fallback": {
                    "base_url": "https://api.example.com/v1",
                    "model": "fallback",
                },
            },
            "router": {"coder_model": "coder", "fallback_model": "fallback"},
            "checks": {"commands": ["python -m pytest -q"], "mypy_enabled": True},
            "sandbox": {
                "default": "docker",
                "docker_image": "python:3.11-slim",
                "docker_network": "none",
                "docker_read_only": True,
                "docker_env": ["PIP_INDEX_URL"],
                "docker_user": "1000:1000",
                "docker_setup_commands": ["python -m pip install -e ."],
                "docker_tmpfs": ["/tmp", "/run"],
            },
        }
    )

    assert config.providers["coder"].base_url == "http://localhost:9999/v1"
    assert config.providers["coder"].timeout_seconds == 33
    assert config.providers["coder"].max_retries == 2
    assert config.providers["coder"].retry_backoff_seconds == 0.25
    assert config.providers["coder"].max_tokens == 4096
    assert config.providers["coder"].input_cost_per_1m == 1.0
    assert config.router.fallback_model == "fallback"
    assert config.checks.enabled_commands() == ("python -m pytest -q", "mypy .")
    assert config.sandbox.default == "docker"
    assert config.sandbox.docker_network == "none"
    assert config.sandbox.docker_read_only is True
    assert config.sandbox.docker_env == ("PIP_INDEX_URL",)
    assert config.sandbox.docker_user == "1000:1000"
    assert config.sandbox.docker_setup_commands == ("python -m pip install -e .",)
    assert config.sandbox.docker_tmpfs == ("/tmp", "/run")


def test_validate_config_reports_invalid_docker_lifecycle_values():
    config = config_from_mapping(
        {"sandbox": {"docker_setup_commands": [""], "docker_tmpfs": ["relative"]}}
    )

    issues = validate_config(config)

    assert any(issue.path == "sandbox.docker_setup_commands.0" for issue in issues)
    assert any(issue.path == "sandbox.docker_tmpfs.0" for issue in issues)


def test_simple_yaml_fallback_shape(tmp_path):
    path = tmp_path / ".gia.yaml"
    path.write_text(
        """
providers:
  coder:
    base_url: http://localhost:8000/v1
    model: local-coder
checks:
  commands:
    - python -m pytest -q
  mypy_enabled: false
""",
        encoding="utf-8",
    )

    config = load_config(tmp_path, path)

    assert config.providers["coder"].model == "local-coder"
    assert config.checks.commands == ("python -m pytest -q",)


def test_sample_config_text_is_loadable(tmp_path):
    path = tmp_path / ".gia.yaml"
    path.write_text(sample_config_text(), encoding="utf-8")

    config = load_config(tmp_path)

    assert config.router.fallback_model is None
    assert config.sandbox.docker_workdir == "/workspace"
    assert validate_config(config) == []


def test_all_config_presets_are_loadable(tmp_path):
    for preset in available_config_presets():
        path = tmp_path / f"{preset}.yaml"
        path.write_text(sample_config_text(preset), encoding="utf-8")

        config = load_config(tmp_path, path)

        assert validate_config(config) == []


def test_validate_config_reports_missing_provider():
    config = config_from_mapping({"router": {"coder_model": "missing"}})

    issues = validate_config(config)

    assert any(issue.severity == "error" for issue in issues)
    assert any(issue.path == "router.coder_model" for issue in issues)


def test_validate_config_reports_bad_provider_runtime_values():
    config = config_from_mapping(
        {
            "providers": {
                "coder": {
                    "timeout_seconds": 0,
                    "max_retries": -1,
                    "retry_backoff_seconds": -0.1,
                    "max_tokens": 0,
                }
            }
        }
    )

    issues = validate_config(config)

    assert any(issue.path == "providers.coder.timeout_seconds" for issue in issues)
    assert any(issue.path == "providers.coder.max_retries" for issue in issues)
    assert any(issue.path == "providers.coder.retry_backoff_seconds" for issue in issues)
    assert any(issue.path == "providers.coder.max_tokens" for issue in issues)
