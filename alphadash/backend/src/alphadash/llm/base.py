"""LLM client interface (S2.3).

Providers differ wildly in SDK shape; the pipeline needs exactly two operations:
- ``complete``: one-shot text completion (suggestion generation, schema-validated downstream)
- ``stream``: incremental text chunks (chat, S2.7)

Messages are plain ``{"role": "user"|"assistant", "content": str}`` dicts. The system prompt is
a separate argument — providers place it wherever their API wants it. Anything fancier
(tool use, thinking config) stays inside the adapter.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Provider call failed after retries, or response was unusable."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> LLMResponse: ...

    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> Iterator[str]: ...
