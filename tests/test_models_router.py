import json
import urllib.error

from issue_agent.config import ProviderConfig
from issue_agent.issue import Issue
from issue_agent.models import ChatMessage, OpenAICompatibleClient
from issue_agent.router import deterministic_file_selection


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

    response = client.complete([ChatMessage(role="user", content="fix")])

    assert captured["url"] == "http://localhost:8000/v1/chat/completions"
    assert captured["payload"]["model"] == "coder-model"
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


def test_issue_prompt_text_includes_title():
    issue = Issue(title="Bug", body="Details", source="test")

    assert issue.prompt_text() == "# Bug\n\nDetails"
