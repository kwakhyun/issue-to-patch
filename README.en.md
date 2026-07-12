# issue-to-patch

[한국어 README](README.md)

`issue-to-patch` provides `gia`, a local-first Python CLI agent for turning
GitHub issues into reviewed, tested git patches.

It protects the target repository by creating an isolated git worktree, asks
OpenAI-compatible model backends for unified diffs, applies and tests patches,
then records run metadata for benchmark and leaderboard use.

## Core Value

This project is not trying to replace interactive coding agents such as Claude
Code or Codex. For fixing one repository with a human in the loop, those tools
are usually the better choice.

The core value of `issue-to-patch` is that it lets you **run multiple AI models
through the same GitHub issue-to-patch workflow, safely produce patches, and
compare the results with data**.

Reasons to use this CLI:

- It experiments in a temporary git worktree instead of editing the original repo directly.
- It outputs reviewable `git diff` patches instead of prose-only AI answers.
- It runs checks such as `pytest`, `ruff`, and optional `mypy`.
- It records attempts, errors, costs, providers, and fallback usage as metadata.
- It compares Ollama, vLLM, and OpenAI-compatible APIs through one interface.
- It fits SWE-bench Lite, selected Verified cases, and custom Korean issue benchmarks.
- It supports resolved-per-dollar style comparisons for model selection.

In one sentence: this CLI is not "the smartest AI coder"; it is a
**local-first issue-to-patch benchmark and automation harness**.

## Status

This project is alpha-quality open source infrastructure. The CLI surface is
usable for local experiments, but generated patches should still be reviewed
before they are trusted.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,yaml]"
```

Check your local setup:

```bash
gia doctor --repo /path/to/python/repo
gia config validate --repo /path/to/python/repo
```

Create a starter config:

```bash
gia init-config --repo /path/to/python/repo
gia init-config --repo /path/to/python/repo --preset ollama
```

## Solve an issue

```bash
gia solve \
  --repo /path/to/python/repo \
  --issue https://github.com/owner/repo/issues/123 \
  --sandbox local \
  --max-iters 3 \
  --repair-strategy replacement \
  --run-dir .gia-runs/issue-123 \
  --out-diff fix.patch \
  --metadata-out runs.jsonl
```

Issue input can be a GitHub issue URL, a local markdown/json file, or inline
text. GitHub issue input also accepts `owner/repo#123`, and `#123` when the
target repository has a GitHub `origin` remote. GitHub issue refs use
`gh issue view` when the GitHub CLI is available.

Use `--sandbox docker` to run validation commands in a Docker container. Local
mode is the default and is recorded explicitly in run metadata.
When a generic image lacks project dependencies, configure
`sandbox.docker_setup_commands`. If installation needs network access, explicitly
select an allowed `docker_network` instead of the default `none`.

By default, `gia solve` refuses to run when the target repository has
uncommitted changes. Pass `--allow-dirty` only when you intentionally want to
solve against the current `HEAD` while preserving unrelated local edits outside
the isolated worktree. Every generated patch is dry-run checked with
`git apply --check` before it is applied.

Use `--run-dir PATH` to save a complete run bundle:

- `final.patch`: final unified diff.
- `metadata.json`: full compact run metadata.
- `attempts.jsonl`: detailed attempt records including check stdout/stderr.
- `summary.json`: the same summary printed to stderr by default.

Debugging options:

- `--base-ref REF` creates the isolated worktree from a specific ref.
- `--keep-worktree never|on-failure|always` preserves the temporary worktree
  for inspection.
- `--repair-strategy replacement|incremental` applies candidates independently
  to the base revision or layers repairs on the previous candidate.
- `--check-command CMD` overrides configured checks and can be repeated.
- `--context-max-files` and `--context-max-chars` bound repository discovery and prompt size.
- `--skip-checks` applies a valid patch but records `status=unchecked`; unchecked
  runs return exit code 2 so CI does not treat them as resolved.
- `--quiet` suppresses stderr summary; `--verbose` prints progress logs.

Schema v2 metadata includes the actual `model_provider`, `model`, `model_route`,
aggregate token usage, `patch_provider`, `fallback_used`, and compact attempt records.
Leaderboards prefer the model that actually generated the patch. Detailed
attempt artifacts cap and redact check stdout/stderr. When solving fails before
metadata exists, `--run-dir` writes `error.json`; use `--error-out PATH` for an
explicit error artifact path.

## Configure Models and Checks

Create `.gia.yaml` in the target repository:

```yaml
providers:
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
```

External fallback providers are opt-in. Keep `fallback_model: null` until you
explicitly want network fallback outside your local model stack.

Available config presets:

- `local`: Ollama for triage and vLLM for coding.
- `ollama`: Ollama-compatible local models for both roles.
- `vllm`: vLLM OpenAI-compatible server for both roles.
- `openai-compatible`: generic external OpenAI-compatible provider template.

## Benchmarks

```bash
gia bench swebench --dataset lite --cases cases.jsonl --limit 10 --predictions preds.jsonl
gia bench korean --cases korean_cases.jsonl --out runs.jsonl
gia bench korean --cases korean_cases.jsonl --out runs.jsonl --solve --limit 10
gia bench korean --cases korean_cases.jsonl --out runs.jsonl --solve --resume --workers 4
gia bench swebench --dataset lite --cases cases.jsonl --predictions preds.jsonl \
  --evaluate-command 'python -m swebench.harness.run_evaluation --predictions_path {predictions}'
gia leaderboard --runs runs.jsonl --sort resolved_per_dollar
```

The SWE-bench command writes prediction JSONL compatible with the official
harness shape (`instance_id`, `model_name_or_path`, `model_patch`). It does not
replace the official Docker evaluation harness.
`--evaluate-command` expands `{predictions}` and `{dataset}` and invokes an installed
official harness without shell evaluation.

`gia bench korean --solve` runs each case through the local solver when a case
includes `repo` plus one of `issue`, `issue_file`, or `issue_text`.
`--resume` skips existing `case_id` values, while `--workers` runs independent cases
with bounded parallelism.

## Development

```bash
python -m pytest
ruff check .
ruff format --check .
mypy src
python -m build
twine check dist/*
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/usage.md](docs/usage.md).

Tagged releases matching `v*` build wheel/sdist artifacts and attach them to a
GitHub Release.
