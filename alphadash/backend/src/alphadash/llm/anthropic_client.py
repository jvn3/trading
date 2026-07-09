"""Anthropic adapter (S2.3). Default model: claude-opus-4-8, adaptive thinking."""

from __future__ import annotations

import os
from collections.abc import Iterator

import anthropic

from alphadash.llm.base import LLMError, LLMResponse


class AnthropicLLM:
    def __init__(self, api_key: str | None = None, model: str = "claude-opus-4-8") -> None:
        # Explicit key wins; otherwise the SDK resolves ANTHROPIC_API_KEY / auth profile itself.
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> LLMResponse:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                messages=messages,
            )
        except anthropic.APIError as e:
            raise LLMError(f"anthropic: {e}") from e
        if response.stop_reason == "refusal":
            raise LLMError("anthropic: request refused by safety classifiers")
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> Iterator[str]:
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                messages=messages,
            ) as stream:
                yield from stream.text_stream
        except anthropic.APIError as e:
            raise LLMError(f"anthropic: {e}") from e


def anthropic_available(api_key: str | None) -> bool:
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))
