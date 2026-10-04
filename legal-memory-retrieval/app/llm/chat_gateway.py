"""Provider-neutral chat gateway for Ask, Assistant, grounding, and edit paths.

Routes to Azure OpenAI when configured (preferred), else Bedrock Mantle.
Keeps call sites from hard-coding a single cloud vendor.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from app.config import settings
from app.llm import azure_openai_client, bedrock_client


def preferred_provider() -> str:
    """Return ``azure``, ``bedrock``, or ``none`` for the active chat backend."""
    for forced in (
        (settings.answer_provider or "").strip().lower(),
        os.environ.get("DEFAULT_LLM_PROVIDER", "").strip().lower(),
    ):
        if forced in {"azure", "azure_openai", "azure-openai"}:
            return "azure" if azure_openai_client.azure_configured() else "none"
        if forced == "bedrock":
            return "bedrock" if bedrock_client.bedrock_configured() else "none"
    if azure_openai_client.azure_configured():
        return "azure"
    if bedrock_client.bedrock_configured():
        return "bedrock"
    return "none"


def chat_configured() -> bool:
    return preferred_provider() != "none"


def writer_model() -> str:
    provider = preferred_provider()
    if provider == "azure":
        return azure_openai_client.resolve_chat_model(settings.azure_openai_deployment)
    if provider == "bedrock":
        return bedrock_client.resolve_chat_model(settings.bedrock_model)
    return settings.azure_openai_deployment or settings.bedrock_model or ""


def chat_complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    provider = preferred_provider()
    if provider == "azure":
        return azure_openai_client.chat_complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            tools=tools,
            timeout=timeout,
        )
    if provider == "bedrock":
        return bedrock_client.chat_complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            tools=tools,
            timeout=timeout,
        )
    raise RuntimeError("no_chat_provider_configured")


def chat_stream(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    timeout: float = 90.0,
) -> Iterator[str]:
    provider = preferred_provider()
    if provider == "azure":
        return azure_openai_client.chat_stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    if provider == "bedrock":
        return bedrock_client.chat_stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    raise RuntimeError("no_chat_provider_configured")


async def achat_complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    provider = preferred_provider()
    if provider == "azure":
        return await azure_openai_client.achat_complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            tools=tools,
            timeout=timeout,
        )
    if provider == "bedrock":
        return await bedrock_client.achat_complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            tools=tools,
            timeout=timeout,
        )
    raise RuntimeError("no_chat_provider_configured")
