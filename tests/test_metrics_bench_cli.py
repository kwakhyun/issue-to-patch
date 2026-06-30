import json
import subprocess

from issue_agent.bench import summarize_korean_benchmark, write_swebench_predictions
from issue_agent.cli import main
from issue_agent.metrics import compute_leaderboard, format_leaderboard, sort_leaderboard


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

    assert "gia 0.1.0" in capsys.readouterr().out


def test_cli_init_config(tmp_path, capsys):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    code = main(["init-config", "--repo", str(tmp_path)])

    assert code == 0
    assert (tmp_path / ".gia.yaml").exists()
    assert "wrote" in capsys.readouterr().out


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
