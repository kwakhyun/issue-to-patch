from __future__ import annotations

import json
import re

from .config import Config, ProviderConfig
from .errors import ModelError
from .issue import Issue
from .models import ChatMessage, ModelResponse, OpenAICompatibleClient

TRIAGE_SYSTEM = (
    "You are a fast repository triage model. Select the smallest useful set of files "
    'for solving the issue. Return JSON only, shaped as {"files": ["path.py"]}.'
)

CODER_SYSTEM = (
    "You are a senior Python maintenance agent. Produce a minimal unified git diff "
    "that fixes the issue. Return only the patch, with no explanation or markdown."
)


class ModelRouter:
    def __init__(self, config: Config, *, model_profile: str | None = None) -> None:
        self.config = config
        self.model_profile = model_profile
        self.last_triage_response: ModelResponse | None = None

    def choose_files(self, issue: Issue, tracked_files: list[str]) -> list[str]:
        provider = self._provider(self.config.router.triage_model)
        if provider is not None:
            prompt = f"Issue:\n{issue.prompt_text()}\n\nRepository files:\n" + "\n".join(
                tracked_files[:400]
            )
            try:
                response = OpenAICompatibleClient(provider).complete(
                    [
                        ChatMessage(role="system", content=TRIAGE_SYSTEM),
                        ChatMessage(role="user", content=prompt),
                    ],
                    temperature=0.0,
                    max_tokens=1500,
                )
                self.last_triage_response = response
                parsed = _parse_file_selection(response.text)
                if parsed:
                    return _existing_files(parsed, tracked_files)
            except ModelError:
                pass
        return deterministic_file_selection(tracked_files)

    def generate_patch(
        self,
        *,
        issue: Issue,
        file_context: str,
        current_diff: str,
        feedback: str | None,
    ) -> ModelResponse:
        user_prompt = (
            f"Issue:\n{issue.prompt_text()}\n\n"
            f"Relevant files:\n{file_context or '(no readable files selected)'}\n\n"
            f"Current diff already applied in the worktree:\n{current_diff or '(none)'}\n\n"
            f"Previous check feedback:\n{feedback or '(none)'}\n\n"
            "Return a unified git diff that can be applied with `git apply`."
        )
        errors: list[str] = []
        for provider in self._patch_providers():
            try:
                return OpenAICompatibleClient(provider).complete(
                    [
                        ChatMessage(role="system", content=CODER_SYSTEM),
                        ChatMessage(role="user", content=user_prompt),
                    ],
                    temperature=0.1,
                )
            except ModelError as exc:
                errors.append(str(exc))
        raise ModelError("No patch provider succeeded: " + " | ".join(errors))

    def _patch_providers(self) -> list[ProviderConfig]:
        names: list[str | None] = []
        if self.model_profile:
            names.append(self.model_profile)
        names.append(self.config.router.coder_model)
        names.append(self.config.router.fallback_model)
        providers: list[ProviderConfig] = []
        seen: set[str] = set()
        for name in names:
            provider = self._provider(name)
            if provider and provider.name not in seen:
                providers.append(provider)
                seen.add(provider.name)
        return providers

    def _provider(self, name: str | None) -> ProviderConfig | None:
        return self.config.provider(name)


def deterministic_file_selection(tracked_files: list[str], *, limit: int = 40) -> list[str]:
    ranked = sorted(tracked_files, key=_rank_file)
    return ranked[:limit]


def _rank_file(path: str) -> tuple[int, str]:
    name = path.rsplit("/", maxsplit=1)[-1]
    if name in {"pyproject.toml", "setup.py", "setup.cfg"}:
        return (0, path)
    if path.endswith(".py") and not path.startswith("tests/"):
        return (1, path)
    if path.endswith(".py"):
        return (2, path)
    return (3, path)


def _parse_file_selection(text: str) -> list[str]:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        return [str(item) for item in data["files"]]
    if isinstance(data, list):
        return [str(item) for item in data]
    files: list[str] = []
    for line in stripped.splitlines():
        candidate = line.strip().strip("-*`'\" ")
        if re.search(r"\.(py|toml|cfg|ini|md|txt)$", candidate):
            files.append(candidate)
    return files


def _existing_files(selected: list[str], tracked_files: list[str]) -> list[str]:
    tracked = set(tracked_files)
    return [file_name for file_name in selected if file_name in tracked]
