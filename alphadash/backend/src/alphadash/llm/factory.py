"""LLM provider selection (S2.3). Keys resolve: explicit ALPHADASH_* setting → bare env var."""

from __future__ import annotations

import os

from alphadash.config import Settings
from alphadash.llm.base import LLMClient
from alphadash.llm.fake import FakeLLM


def build_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "fake":
        return FakeLLM()

    if provider == "anthropic":
        from alphadash.llm.anthropic_client import AnthropicLLM

        key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        return AnthropicLLM(api_key=key, model=settings.anthropic_model)

    if provider == "openai":
        from alphadash.llm.openai_client import OpenAICompatLLM

        key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("llm_provider=openai but no OPENAI_API_KEY configured")
        return OpenAICompatLLM(api_key=key, model=settings.openai_model)

    if provider == "github":
        from alphadash.llm.openai_client import OpenAICompatLLM

        key = settings.github_token or os.environ.get("GITHUB_TOKEN")
        if not key:
            raise RuntimeError("llm_provider=github but no GITHUB_TOKEN configured")
        return OpenAICompatLLM(
            api_key=key,
            model=settings.github_model,
            base_url=settings.github_base_url,
            provider_name="github",
        )

    raise RuntimeError(f"unknown llm_provider {settings.llm_provider!r}")
