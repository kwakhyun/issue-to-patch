# Usage

## Initialize config

```bash
gia init-config --repo /path/to/repo
```

This writes `.gia.yaml` with local Ollama/vLLM defaults and safe check settings.
The repo path must already exist and be a git repository; `gia` will not create
directories from a mistyped path.

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
  --out-diff fix.patch \
  --metadata-out runs.jsonl
```

Use `--diff-only` to request a patch without applying it in the isolated
worktree. Use `--sandbox docker` for test execution in Docker.

## Leaderboard

```bash
gia leaderboard --runs runs.jsonl
gia leaderboard --runs runs.jsonl --json
```

Local zero-cost runs are reported separately from paid resolved-per-dollar
scores.
