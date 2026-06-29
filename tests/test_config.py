from issue_agent.config import config_from_mapping, load_config


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
                    "input_cost_per_1m": 1.0,
                },
                "fallback": {
                    "base_url": "https://api.example.com/v1",
                    "model": "fallback",
                },
            },
            "router": {"coder_model": "coder", "fallback_model": "fallback"},
            "checks": {"commands": ["python -m pytest -q"], "mypy_enabled": True},
            "sandbox": {"default": "docker", "docker_image": "python:3.11-slim"},
        }
    )

    assert config.providers["coder"].base_url == "http://localhost:9999/v1"
    assert config.providers["coder"].input_cost_per_1m == 1.0
    assert config.router.fallback_model == "fallback"
    assert config.checks.enabled_commands() == ("python -m pytest -q", "mypy .")
    assert config.sandbox.default == "docker"


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
