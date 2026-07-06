# issue-to-patch

[English README](README.en.md)

`issue-to-patch`는 GitHub issue를 검토 가능한 테스트된 git patch로 바꾸기 위한
local-first Python CLI agent입니다. CLI 명령은 `gia`입니다.

대상 저장소를 보호하기 위해 격리된 git worktree를 만들고,
OpenAI-compatible 모델 백엔드에 unified diff 생성을 요청한 뒤, patch 적용과
검증 명령을 실행합니다. 실행 metadata는 benchmark와 leaderboard에 사용할 수
있도록 기록됩니다.

## 핵심 가치

이 도구는 Claude Code나 Codex 같은 대화형 coding agent를 대체하려는 도구가
아닙니다. 개별 repo 하나를 빠르게 고치는 목적이라면 그런 도구를 직접 쓰는 것이
더 좋습니다.

`issue-to-patch`의 핵심 가치는 **여러 AI 모델을 같은 GitHub issue 해결 흐름에서
반복 실행하고, 안전하게 patch를 만들고, 결과를 숫자로 비교할 수 있게 하는 것**입니다.

이 CLI를 써야 하는 이유:

- 원본 repo를 직접 건드리지 않고 임시 worktree에서 patch를 실험합니다.
- AI 답변을 설명이 아니라 리뷰 가능한 `git diff`로 남깁니다.
- `pytest`, `ruff`, 선택적 `mypy` 같은 검사를 자동 실행합니다.
- 실패해도 attempt, error, cost, provider, fallback 여부를 metadata로 남깁니다.
- Ollama, vLLM, OpenAI-compatible API를 같은 방식으로 비교할 수 있습니다.
- SWE-bench Lite, 일부 Verified, 자체 Korean issue benchmark 같은 평가 흐름에 맞습니다.
- `resolved / $`처럼 비용 대비 해결률을 계산해 모델 선택을 데이터로 할 수 있습니다.

한 줄로 말하면, 이 CLI는 “가장 똑똑한 AI 코더”가 아니라
**로컬 우선 issue-to-patch benchmark/automation harness**입니다.

## 상태

이 프로젝트는 alpha 품질의 오픈소스 인프라입니다. CLI 표면은 로컬 실험에
사용할 수 있지만, 생성된 patch는 신뢰하기 전에 반드시 사람이 검토해야 합니다.

## 설치

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,yaml]"
```

로컬 환경을 점검합니다.

```bash
gia doctor --repo /path/to/python/repo
gia config validate --repo /path/to/python/repo
```

초기 설정 파일을 만듭니다.

```bash
gia init-config --repo /path/to/python/repo
gia init-config --repo /path/to/python/repo --preset ollama
```

## Issue 해결

```bash
gia solve \
  --repo /path/to/python/repo \
  --issue https://github.com/owner/repo/issues/123 \
  --sandbox local \
  --max-iters 3 \
  --run-dir .gia-runs/issue-123 \
  --out-diff fix.patch \
  --metadata-out runs.jsonl
```

Issue 입력은 GitHub issue URL, 로컬 markdown/json 파일, inline text를 지원합니다.
GitHub issue 입력은 `owner/repo#123` 형식도 지원하며, 대상 저장소의 `origin`
remote가 GitHub라면 `#123` 형식도 사용할 수 있습니다. GitHub issue ref는
GitHub CLI가 있을 때 `gh issue view`로 가져옵니다.

검증 명령을 Docker container 안에서 실행하려면 `--sandbox docker`를 사용합니다.
기본값은 local mode이며, 실행 metadata에도 명시적으로 기록됩니다.

기본적으로 `gia solve`는 대상 저장소에 uncommitted change가 있으면 실행을
거부합니다. 현재 `HEAD` 기준으로 worktree를 만들되 관련 없는 로컬 변경은
원본 저장소에 그대로 두고 싶을 때만 `--allow-dirty`를 사용하세요. 생성된 모든
patch는 적용 전에 `git apply --check`로 dry-run 검증됩니다.

`--run-dir PATH`를 사용하면 전체 실행 bundle을 저장합니다.

- `final.patch`: 최종 unified diff.
- `metadata.json`: compact run metadata 전체.
- `attempts.jsonl`: check stdout/stderr를 포함한 상세 attempt 기록.
- `summary.json`: 기본적으로 stderr에 출력되는 summary와 같은 내용.

디버깅 옵션:

- `--base-ref REF`: 특정 ref에서 격리 worktree를 생성합니다.
- `--keep-worktree never|on-failure|always`: 임시 worktree를 inspection용으로 보존합니다.
- `--check-command CMD`: 설정 파일의 checks를 override합니다. 여러 번 지정할 수 있습니다.
- `--skip-checks`: 유효한 patch를 적용하되 `status=unchecked`로 기록합니다. unchecked
  run은 CI가 resolved로 오해하지 않도록 exit code 2를 반환합니다.
- `--quiet`: stderr summary를 숨깁니다.
- `--verbose`: 진행 로그를 stderr에 출력합니다.

실행 metadata에는 `schema_version`, `run_id`, `patch_provider`,
`fallback_used`, compact attempt 기록이 포함됩니다. 상세 attempt artifact는
check stdout/stderr를 size cap과 secret redaction을 거쳐 저장합니다. metadata가
생성되기 전에 실패하면 `--run-dir`에 `error.json`을 쓰며, `--error-out PATH`로
명시적인 error artifact 경로를 지정할 수 있습니다.

## 모델과 검증 명령 설정

대상 저장소에 `.gia.yaml`을 만듭니다.

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
```

외부 fallback provider는 opt-in입니다. 로컬 모델 stack 밖의 네트워크 fallback을
명시적으로 원할 때까지 `fallback_model: null`을 유지하세요.

사용 가능한 config preset:

- `local`: triage는 Ollama, coding은 vLLM 사용.
- `ollama`: 두 역할 모두 Ollama-compatible local model 사용.
- `vllm`: 두 역할 모두 vLLM OpenAI-compatible server 사용.
- `openai-compatible`: generic external OpenAI-compatible provider template.

## Benchmark

```bash
gia bench swebench --dataset lite --cases cases.jsonl --limit 10 --predictions preds.jsonl
gia bench korean --cases korean_cases.jsonl --out runs.jsonl
gia bench korean --cases korean_cases.jsonl --out runs.jsonl --solve --limit 10
gia leaderboard --runs runs.jsonl --sort resolved_per_dollar
```

SWE-bench 명령은 공식 harness shape와 호환되는 prediction JSONL을 작성합니다.
필드는 `instance_id`, `model_name_or_path`, `model_patch`입니다. 이 명령은 공식
Docker evaluation harness를 대체하지 않습니다.

`gia bench korean --solve`는 case에 `repo`와 `issue`, `issue_file`,
`issue_text` 중 하나가 포함되어 있을 때 각 case를 local solver로 실행합니다.

## 개발

```bash
python -m pytest
ruff check .
ruff format --check .
mypy src
python -m build
twine check dist/*
```

[CONTRIBUTING.md](CONTRIBUTING.md)와 [docs/usage.md](docs/usage.md)를 참고하세요.

`v*` 형식의 tag release는 wheel/sdist artifact를 build하고 GitHub Release에
첨부합니다.
