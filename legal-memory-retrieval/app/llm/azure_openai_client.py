"""Azure OpenAI / AI Foundry client (OpenAI-compatible /openai/v1).

Uses httpx only — no Azure SDK dependency (see docs/AZURE_DEPLOYMENT_ROADMAP.md G1/G9).
Auth: api-key header (also sent as Bearer for Foundry compatibility).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Registry URI → chat deployment name (Azure chat API requires a deployment id).
AZURE_MODEL_ALIASES: dict[str, str] = {
    "azureml://registries/azureml-deepseek/models/DeepSeek-V4-Flash/versions/2026-04-23": (
        "DeepSeek-V4-Flash"
    ),
    "DeepSeek-V4-Flash-2026-04-23": "DeepSeek-V4-Flash",
}


def azure_api_key() -> str:
    return (
        (settings.azure_openai_api_key or "").strip()
        or os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    )


def azure_configured() -> bool:
    return bool(azure_api_key() and azure_endpoint())


def azure_endpoint() -> str:
    raw = (
        (settings.azure_openai_endpoint or "").strip()
        or os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    )
    return raw.rstrip("/")


def resolve_chat_model(model: str | None) -> str:
    raw = (
        model
        or settings.azure_openai_deployment
        or "DeepSeek-V4-Flash"
    ).strip()
    return AZURE_MODEL_ALIASES.get(raw, raw)


def _auth_headers() -> dict[str, str]:
    key = azure_api_key()
    if not key:
        raise ValueError("AZURE_OPENAI_API_KEY is not configured")
    return {
        "api-key": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _chat_url() -> str:
    base = azure_endpoint()
    if not base:
        raise ValueError("AZURE_OPENAI_ENDPOINT is not configured")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


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
    """OpenAI-compatible chat completions on Azure.

    Returns a normalized dict: {content, tool_calls, model, raw}.
    """
    model_id = resolve_chat_model(model)
    body: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(_chat_url(), headers=_auth_headers(), json=body)
        if resp.status_code >= 400:
            logger.warning(
                "Azure OpenAI chat error model=%s status=%s body=%s",
                model_id,
                resp.status_code,
                resp.text[:500],
            )
        resp.raise_for_status()
        data = resp.json()

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "content": message.get("content") or "",
        "tool_calls": message.get("tool_calls") or [],
        "model": model_id,
        "usage": data.get("usage") or {},
        "finish_reason": choice.get("finish_reason"),
        "raw": data,
    }


def chat_stream(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    timeout: float = 90.0,
) -> Iterator[str]:
    """Stream text deltas from Azure OpenAI (``stream: true``)."""
    model_id = resolve_chat_model(model)
    body: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", _chat_url(), headers=_auth_headers(), json=body) as resp:
            if resp.status_code >= 400:
                resp.read()
                logger.warning(
                    "Azure OpenAI stream error model=%s status=%s body=%s",
                    model_id,
                    resp.status_code,
                    resp.text[:500],
                )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield delta


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
    """Async variant of chat_complete."""
    model_id = resolve_chat_model(model)
    body: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_chat_url(), headers=_auth_headers(), json=body)
        if resp.status_code >= 400:
            logger.warning(
                "Azure OpenAI chat error model=%s status=%s body=%s",
                model_id,
                resp.status_code,
                resp.text[:500],
            )
        resp.raise_for_status()
        data = resp.json()

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {
        "content": message.get("content") or "",
        "tool_calls": message.get("tool_calls") or [],
        "model": model_id,
        "usage": data.get("usage") or {},
        "finish_reason": choice.get("finish_reason"),
        "raw": data,
    }
