import json
import subprocess
import sys

from issue_agent.bench import (
    run_korean_benchmark,
    run_swebench_harness,
    summarize_korean_benchmark,
    write_swebench_predictions,
)
from issue_agent.cli import main
from issue_agent.errors import GiaError
from issue_agent.metrics import compute_leaderboard, format_leaderboard, sort_leaderboard
from issue_agent.models import ModelResponse

PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


class FakeOpenAIClient:
    def __init__(self, config):
        self.config = config

    def complete(self, messages, **kwargs):
        text = '{"files": ["app.py"]}' if self.config.name == "triage" else PATCH
        return ModelResponse(
            text=text,
            provider=self.config.name,
            model=self.config.model,
            input_tokens=10,
            output_tokens=20,
            cost_usd=0.01,
        )


def _init_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_compute_leaderboard_zero_cost_and_paid():
    rows = sort_leaderboard(
        compute_leaderboard(
            [
                {"model_profile": "local", "resolved": True, "cost_usd": 0},
                {"model_profile": "paid", "resolved": True, "cost_usd": 0.5},
                {"model_profile": "paid", "resolved": False, "cost_usd": 0.5},
            ]
        )
    )

    assert rows[0].model_profile == "paid"
    assert rows[0].resolved_per_dollar == 1.0
    assert rows[1].zero_cost
    assert "resolved/$" in format_leaderboard(rows)


def test_compute_leaderboard_prefers_actual_provider_and_model():
    rows = compute_leaderboard(
        [
            {
                "model_profile": "requested-profile",
                "model_provider": "ollama",
                "model": "qwen3-coder",
                "resolved": True,
                "cost_usd": 0,
            },
            {
                "model_profile": "requested-profile",
                "model_provider": "vllm",
                "model": "deepseek-coder",
                "resolved": False,
                "cost_usd": 0,
            },
        ]
    )

    assert {row.model_profile for row in rows} == {
        "ollama:qwen3-coder",
        "vllm:deepseek-coder",
    }


def test_write_swebench_predictions(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps({"instance_id": "x", "patch": "diff --git a/a.py b/a.py"}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "preds.jsonl"

    count = write_swebench_predictions(
        predictions_path=out, dataset="lite", limit=1, cases_path=cases, model_name="m"
    )

    line = json.loads(out.read_text(encoding="utf-8"))
    assert count == 1
    assert line["instance_id"] == "x"
    assert line["model_name_or_path"] == "m"


def test_swebench_harness_adapter_expands_placeholders(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    predictions = tmp_path / "predictions.jsonl"

    code = run_swebench_harness(
        command="python -m harness --predictions {predictions} --dataset {dataset}",
        predictions_path=predictions,
        dataset="lite",
    )

    assert code == 0
    assert str(predictions.resolve()) in captured["args"]
    assert captured["args"][-1] == "lite"


def test_swebench_harness_rejects_non_positive_timeout(tmp_path):
    try:
        run_swebench_harness(
            command="python -V",
            predictions_path=tmp_path / "predictions.jsonl",
            dataset="lite",
            timeout_seconds=0,
        )
    except GiaError as exc:
        assert "timeout must be positive" in str(exc)
    else:
        raise AssertionError("non-positive timeout should be rejected")


def test_summarize_korean_benchmark(tmp_path):
    cases = tmp_path / "korean.json"
    cases.write_text(
        json.dumps([{"id": "kr-1", "resolved": True, "cost_usd": 0.1}]),
        encoding="utf-8",
    )
    out = tmp_path / "runs.jsonl"

    count = summarize_korean_benchmark(cases_path=cases, out_path=out)

    assert count == 1
    assert json.loads(out.read_text(encoding="utf-8"))["resolved"]


def test_cli_leaderboard(tmp_path, capsys):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"model_profile": "m", "resolved": True, "cost_usd": 1}) + "\n")

    code = main(["leaderboard", "--runs", str(runs)])

    captured = capsys.readouterr()
    assert code == 0
    assert "model_profile" in captured.out
    assert "m" in captured.out


def test_cli_leaderboard_json(tmp_path, capsys):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"model_profile": "m", "resolved": True, "cost_usd": 1}) + "\n")

    code = main(["leaderboard", "--runs", str(runs), "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)[0]["model_profile"] == "m"


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    assert "gia 0.2.0" in capsys.readouterr().out


def test_cli_init_config(tmp_path, capsys):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    code = main(["init-config", "--repo", str(tmp_path)])

    assert code == 0
    assert (tmp_path / ".gia.yaml").exists()
    assert "wrote" in capsys.readouterr().out


def test_cli_init_config_preset(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    code = main(["init-config", "--repo", str(tmp_path), "--preset", "ollama"])

    assert code == 0
    assert "qwen3-coder:latest" in (tmp_path / ".gia.yaml").read_text(encoding="utf-8")


def test_cli_init_config_refuses_overwrite(tmp_path, capsys):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".gia.yaml").write_text("existing: true\n", encoding="utf-8")

    code = main(["init-config", "--repo", str(tmp_path)])

    assert code == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_init_config_requires_existing_repo(tmp_path, capsys):
    missing = tmp_path / "missing"

    code = main(["init-config", "--repo", str(missing)])

    assert code == 1
    assert "does not exist" in capsys.readouterr().err


def test_cli_config_validate(tmp_path, capsys):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    main(["init-config", "--repo", str(tmp_path)])
    capsys.readouterr()

    code = main(["config", "validate", "--repo", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["ok"] is True


def test_cli_solve_run_dir_writes_artifacts(monkeypatch, tmp_path, capsys):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    run_dir = tmp_path / "run"
    check = f"{sys.executable} -c \"print('override-check')\""

    code = main(
        [
            "solve",
            "--repo",
            str(tmp_path),
            "--issue-text",
            "Update value\n\nChange VALUE to 2",
            "--check-command",
            check,
            "--run-dir",
            str(run_dir),
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "+VALUE = 2" in captured.out
    assert json.loads(captured.err)["status"] == "resolved"
    assert (run_dir / "final.patch").exists()
    assert (run_dir / "metadata.json").exists()
    assert (run_dir / "summary.json").exists()
    attempts = [json.loads(line) for line in (run_dir / "attempts.jsonl").read_text().splitlines()]
    assert attempts[0]["checks"][0]["stdout"].strip() == "override-check"


def test_cli_solve_summary_attempts_quiet(monkeypatch, tmp_path, capsys):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    summary_out = tmp_path / "summary.json"
    attempts_out = tmp_path / "attempts.jsonl"

    code = main(
        [
            "solve",
            "--repo",
            str(tmp_path),
            "--issue-text",
            "Update value",
            "--skip-checks",
            "--quiet",
            "--summary-out",
            str(summary_out),
            "--attempts-out",
            str(attempts_out),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(summary_out.read_text(encoding="utf-8"))
    attempt = json.loads(attempts_out.read_text(encoding="utf-8"))
    assert code == 2
    assert captured.err == ""
    assert summary["status"] == "unchecked"
    assert attempt["patch_applied"] is True
    assert attempt["checks"] == []


def test_cli_solve_verbose_logs_to_stderr(monkeypatch, tmp_path, capsys):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)

    code = main(
        [
            "solve",
            "--repo",
            str(tmp_path),
            "--issue-text",
            "Update value",
            "--skip-checks",
            "--verbose",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "[gia] loading issue input" in captured.err
    assert "[gia] iteration 1: applying patch" in captured.err


def test_cli_solve_writes_error_artifact(tmp_path, capsys):
    run_dir = tmp_path / "run"
    error_out = tmp_path / "error.json"

    code = main(
        [
            "solve",
            "--repo",
            str(tmp_path),
            "--issue-file",
            str(tmp_path / "missing.md"),
            "--run-dir",
            str(run_dir),
            "--error-out",
            str(error_out),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads((run_dir / "error.json").read_text(encoding="utf-8"))
    assert code == 1
    assert "Issue file does not exist" in captured.err
    assert payload["schema_version"] == "gia.error.v1"
    assert payload["run_id"] == json.loads(error_out.read_text(encoding="utf-8"))["run_id"]


def test_cli_korean_benchmark_can_run_solve(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    monkeypatch.setattr("issue_agent.router.OpenAICompatibleClient", FakeOpenAIClient)
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "id": "kr-1",
                "repo": str(tmp_path),
                "issue_text": "Update value\n\nChange VALUE to 2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "runs.jsonl"

    code = main(
        [
            "bench",
            "korean",
            "--cases",
            str(cases),
            "--out",
            str(out),
            "--solve",
            "--skip-checks",
            "--allow-dirty",
        ]
    )

    record = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert record["benchmark"] == "korean"
    assert record["case_id"] == "kr-1"
    assert record["status"] == "unchecked"


def test_korean_benchmark_resume_skips_completed_cases(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        "\n".join(
            [
                json.dumps({"id": "kr-1", "repo": str(tmp_path), "issue_text": "one"}),
                json.dumps({"id": "kr-2", "repo": None, "issue_text": "two"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "runs.jsonl"
    out.write_text(json.dumps({"case_id": "kr-1", "status": "resolved"}) + "\n")

    count = run_korean_benchmark(
        cases_path=cases,
        out_path=out,
        resume=True,
        workers=2,
    )

    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert count == 1
    assert [record["case_id"] for record in records] == ["kr-1", "kr-2"]
