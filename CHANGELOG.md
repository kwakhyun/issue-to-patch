# Changelog

All notable changes to this project will be documented in this file.

The project follows semantic versioning once tagged releases begin.

## 0.2.0 - Unreleased

- Added metadata schema v2 with actual provider/model routing, aggregate token usage,
  and model-level leaderboard attribution.
- Added replacement-first repair attempts with an incremental compatibility mode.
- Added Docker setup commands and writable tmpfs lifecycle configuration.
- Added issue-ranked large-repository context discovery and explicit context budgets.
- Added resumable and parallel Korean benchmark runs plus a SWE-bench harness adapter.
- Added automatic solve-time config validation, Python 3.13 CI, and release smoke tests.

## 0.1.0 - Initial development

- Initial local-first GitHub issue agent scaffold.
- Added issue ingestion, git worktree isolation, OpenAI-compatible providers,
  patch validation, check execution, benchmark helpers, and leaderboard output.
- Added open source project metadata, CI, diagnostics, config validation, safer
  config initialization, provider timeout/retry settings, solve dirty-repo
  policy, patch dry-run checks, config presets, release workflow, and issue/PR
  templates.
- Added solve run artifact outputs, worktree debugging controls, check override
  options, quiet/verbose output modes, and GitHub issue shorthand input.
- Added correctness guardrails for unchecked runs, hardened solve artifacts,
  Docker sandbox controls, Korean benchmark solve mode, provider max-token
  settings, model probe reuse, and fallback provider metadata.
