# Security Policy

`issue-to-patch` runs commands against local repositories and can optionally run
inside Docker. Treat untrusted repositories, issues, patches, and model output
as untrusted input.

## Supported versions

The project is pre-1.0. Security fixes target the latest `main` branch until
tagged releases are established.

## Reporting vulnerabilities

Open a private security advisory on GitHub when available, or contact the
maintainer out of band before publishing exploit details.

## Operational guidance

- Prefer `--sandbox docker` for repositories you do not fully trust.
- Review generated diffs before applying them to important branches.
- Do not place API keys in `.gia.yaml`; use `api_key_env` and environment
  variables.
- Keep benchmark datasets and run metadata free of private source code unless
  the repository is private and access-controlled.

