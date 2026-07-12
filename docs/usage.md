# Usage

## Initialize config

```bash
gia init-config --repo /path/to/repo
gia init-config --repo /path/to/repo --preset vllm
```

This writes `.gia.yaml` with local Ollama/vLLM defaults and safe check settings.
The repo path must already exist and be a git repository; `gia` will not create
directories from a mistyped path.

Available presets are `local`, `ollama`, `vllm`, and `openai-compatible`.

## Validate config

```bash
gia config validate --repo /path/to/repo
gia config validate --repo /path/to/repo --json
```

Validation checks provider references, required model fields, cost metadata,
check commands, and sandbox settings without contacting model endpoints.

## Run diagnostics

```bash
gia doctor --repo /path/to/repo
gia doctor --repo /path/to/repo --json
gia doctor --repo /path/to/repo --probe-models
```

`doctor` checks the Python runtime, local tools, git repository state, config
loading, configured checks, and provider secret environment variables. It does
not probe model endpoints unless `--probe-models` is passed, in which case it
checks configured OpenAI-compatible `/models` endpoints.

## Solve

```bash
gia solve \
  --repo /path/to/repo \
  --issue-file issue.md \
  --run-dir .gia-runs/issue-123 \
  --out-diff fix.patch \
  --metadata-out runs.jsonl
```

Use `--diff-only` to request a patch without applying it in the isolated
worktree. Use `--sandbox docker` for test execution in Docker.

`gia solve` refuses dirty target repositories by default. Use `--allow-dirty`
only when the current uncommitted changes are unrelated and you still want GIA
to build an isolated worktree from `HEAD`. Patch attempts include failure-stage
metadata and pass `git apply --check` before application.

Issue input accepts GitHub URLs, `owner/repo#123`, and `#123` when the target
repository has a GitHub `origin` remote. GitHub refs are fetched with
`gh issue view`; save the issue as markdown or JSON and pass `--issue-file`
when `gh` is unavailable.

`--run-dir PATH` writes `final.patch`, `metadata.json`, `attempts.jsonl`, and
`summary.json` for the run. Use `--summary-out` and `--attempts-out` to write
those artifacts to explicit standalone paths. Use `--error-out PATH` when you
also want machine-readable error JSON for failures that happen before solve
metadata exists.

Operational controls:

- `--base-ref REF`: create the temporary worktree from a specific ref.
- `--keep-worktree never|on-failure|always`: preserve the worktree for debugging.
- `--check-command CMD`: override configured checks; repeat for multiple checks.
- `--skip-checks`: apply the patch and record `status=unchecked`; unchecked
  exits with code 2.
- `--check-timeout SECONDS`: override validation command timeout.
- `--quiet` / `--verbose`: suppress summary or emit progress logs on stderr.

Detailed attempt artifacts cap and redact check stdout/stderr. Schema v2 solve
metadata records the actual provider/model route, aggregate token usage, context
counts, repair strategy, `patch_provider`, and `fallback_used`.

## Leaderboard

```bash
gia leaderboard --runs runs.jsonl
gia leaderboard --runs runs.jsonl --json
```

Local zero-cost runs are reported separately from paid resolved-per-dollar
scores.

## Korean Benchmark Solve Mode

```bash
gia bench korean --cases korean_cases.jsonl --out runs.jsonl --solve --limit 10
gia bench korean --cases korean_cases.jsonl --out runs.jsonl --solve --resume --workers 4
```

With `--solve`, each case must include `repo` and exactly one of `issue`,
`issue_file`, or `issue_text`. The command runs the same isolated worktree
solver used by `gia solve` and writes one run metadata record per case.
Resume mode appends records while skipping existing `case_id` values.

Docker sandbox defaults to `docker_network: none`. Docker runs can also be
configured with `docker_read_only`, `docker_env`, `docker_user`,
`docker_setup_commands`, and writable `docker_tmpfs` mounts in `.gia.yaml`.
SWE-bench prediction generation accepts `--evaluate-command` with
`{predictions}` and `{dataset}` placeholders for an installed official harness.

## Release

Push a tag such as `v0.2.0` to run the release workflow. The workflow builds the
source distribution and wheel, checks package metadata, smoke-tests a clean wheel
installation, and attaches artifacts to a GitHub Release.
