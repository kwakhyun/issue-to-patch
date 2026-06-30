# Contributing

Thanks for helping improve `issue-to-patch`.

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,yaml]"
```

## Checks

Run these before opening a pull request:

```bash
python -m pytest
ruff check .
ruff format --check .
mypy src
python -m build
twine check dist/*
```

## Pull requests

- Keep changes focused and include tests for behavior changes.
- Do not include generated caches, local virtualenvs, credentials, or benchmark data dumps.
- For model-provider changes, document the provider shape and avoid hardcoding secrets.
- For benchmark changes, keep fixtures small enough for CI.

