"""OpenAI-compatible adapter (S2.3): OpenAI itself, and GitHub Models (Copilot) via base_url.

GitHub Models exposes an OpenAI-compatible inference endpoint (models.github.ai) authenticated
with a GitHub PAT carrying ``models:read`` — same adapter, different base_url + key.
"""

from __future__ import annotations

from collections.abc import Iterator

import openai

from alphadash.llm.base import LLMError, LLMResponse


class OpenAICompatLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai",
    ) -> None:
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._provider = provider_name

    @property
    def model(self) -> str:
        return self._model

    def _messages(self, system: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}, *messages]

    def complete(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> LLMResponse:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(system, messages),
                max_tokens=max_tokens,  # widest OpenAI-compat support (incl. GitHub Models)
            )
        except openai.OpenAIError as e:
            raise LLMError(f"{self._provider}: {e}") from e
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> Iterator[str]:
        try:
            chunks = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages(system, messages),
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in chunks:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.OpenAIError as e:
            raise LLMError(f"{self._provider}: {e}") from e
