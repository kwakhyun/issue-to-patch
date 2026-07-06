import json
import urllib.error

from issue_agent.config import ProviderConfig, config_from_mapping
from issue_agent.issue import Issue
from issue_agent.models import ChatMessage, OpenAICompatibleClient, probe_provider_models
from issue_agent.router import ModelRouter, deterministic_file_selection


class FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        content = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-a\n+b"
        return json.dumps(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        ).encode("utf-8")


def test_openai_compatible_client_shapes_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeHTTPResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAICompatibleClient(
        ProviderConfig(
            name="coder",
            base_url="http://localhost:8000/v1",
            model="coder-model",
            input_cost_per_1m=1.0,
            output_cost_per_1m=2.0,
        )
    )

    response = client.complete(
        [ChatMessage(role="user", content="fix")],
        max_tokens=123,
        response_format={"type": "json_object"},
    )

    assert captured["url"] == "http://localhost:8000/v1/chat/completions"
    assert captured["payload"]["model"] == "coder-model"
    assert captured["payload"]["max_tokens"] == 123
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 120
    assert response.cost_usd == 0.0002


def test_openai_compatible_client_retries(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("temporary")
        return FakeHTTPResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))
    client = OpenAICompatibleClient(
        ProviderConfig(
            name="coder",
            base_url="http://localhost:8000/v1",
            model="coder-model",
            timeout_seconds=9,
            max_retries=1,
            retry_backoff_seconds=0.25,
        )
    )

    response = client.complete([ChatMessage(role="user", content="fix")])

    assert response.provider == "coder"
    assert calls["count"] == 2
    assert sleeps == [0.25]


def test_deterministic_file_selection_prefers_python_sources():
    files = ["README.md", "tests/test_app.py", "src/app.py", "pyproject.toml"]

    assert deterministic_file_selection(files, limit=3) == [
        "pyproject.toml",
        "src/app.py",
        "tests/test_app.py",
    ]


def test_router_falls_back_when_triage_selects_no_existing_files(monkeypatch):
    class BadTriageClient:
        def __init__(self, config):
            self.config = config

        def complete(self, messages, **kwargs):
            return type(
                "Response",
                (),
                {
                    "text": '{"files": ["missing.py"]}',
                    "cost_usd": 0.0,
                    "provider": self.config.name,
                    "model": self.config.model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                },
            )()

    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", BadTriageClient)
    router = ModelRouter(config_from_mapping({}))

    selected = router.choose_files(
        Issue(title="Bug", body="Details", source="test"),
        ["README.md", "src/app.py", "tests/test_app.py"],
    )

    assert selected[0] == "src/app.py"


def test_provider_probe_reports_status(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://localhost:8000/v1/models"
        assert timeout == 10
        return type(
            "Response",
            (),
            {
                "status": 200,
                "__enter__": lambda self: self,
                "__exit__": lambda self, *args: None,
            },
        )()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = probe_provider_models(
        ProviderConfig(name="coder", base_url="http://localhost:8000/v1", model="m")
    )

    assert result.ok
    assert result.status == 200


def test_issue_prompt_text_includes_title():
    issue = Issue(title="Bug", body="Details", source="test")

    assert issue.prompt_text() == "# Bug\n\nDetails"
