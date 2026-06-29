# GitHub Issue Agent

`gia` is a local-first Python CLI scaffold for solving GitHub issues in Python
repositories. It protects the target repository by creating an isolated git
worktree, asks OpenAI-compatible model backends for unified diffs, applies and
tests patches, then records run metadata for benchmark and leaderboard use.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Solve an issue

```bash
gia solve \
  --repo /path/to/python/repo \
  --issue https://github.com/owner/repo/issues/123 \
  --sandbox local \
  --max-iters 3 \
  --out-diff fix.patch \
  --metadata-out runs.jsonl
```

Issue input can be a GitHub issue URL, a local markdown/json file, or inline
text. GitHub URLs use `gh issue view` when the GitHub CLI is available.

## Configure models and checks

Create `.gia.yaml` in the target repository:

```yaml
providers:
  triage:
    base_url: http://localhost:11434/v1
    model: qwen3:4b
    role: triage
  coder:
    base_url: http://localhost:8000/v1
    model: Qwen/Qwen3-Coder-30B-A3B-Instruct
    role: coder
  fallback:
    base_url: https://api.example.com/v1
    api_key_env: EXTERNAL_API_KEY
    model: fallback-coder
    role: fallback
router:
  triage_model: triage
  coder_model: coder
  fallback_model: fallback
checks:
  commands:
    - python -m pytest
    - ruff check .
  mypy_enabled: false
sandbox:
  default: local
  docker_image: python:3.11
```

## Benchmarks

```bash
gia bench swebench --dataset lite --cases cases.jsonl --limit 10 --predictions preds.jsonl
gia bench korean --cases korean_cases.jsonl --out runs.jsonl
gia leaderboard --runs runs.jsonl --sort resolved_per_dollar
```

The SWE-bench command writes prediction JSONL compatible with the official
harness shape (`instance_id`, `model_name_or_path`, `model_patch`). It does not
replace the official Docker evaluation harness.

