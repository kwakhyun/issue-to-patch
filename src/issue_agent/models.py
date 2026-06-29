from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import ProviderConfig
from .errors import ModelError


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class OpenAICompatibleClient:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        if not self.config.base_url:
            raise ModelError(f"Provider {self.config.name} has no base_url")
        if not self.config.model:
            raise ModelError(f"Provider {self.config.name} has no model")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        request = urllib.request.Request(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ModelError(f"Provider {self.config.name} request failed: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelError(f"Provider {self.config.name} returned invalid JSON") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError(
                f"Provider {self.config.name} response did not include message text"
            ) from exc
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        cost_usd = self._cost(input_tokens=input_tokens, output_tokens=output_tokens)
        return ModelResponse(
            text=str(text),
            provider=self.config.name,
            model=self.config.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            api_key = os.environ.get(self.config.api_key_env)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _cost(self, *, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.config.input_cost_per_1m / 1_000_000
            + output_tokens * self.config.output_cost_per_1m / 1_000_000
        )
