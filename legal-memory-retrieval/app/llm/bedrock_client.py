"""Amazon Bedrock client via bearer-token auth (AWS_BEARER_TOKEN_BEDROCK).

Uses httpx only — no boto3/openai SDK dependency.
Chat: bedrock-mantle OpenAI-compatible Chat Completions.
Embeddings: bedrock-runtime InvokeModel.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Catalog of DMS-supported Bedrock chat models (smoke / selection UI).
# Note: openai.gpt-*-luna/sol/terra appear in Mantle catalog but often need
# marketplace/sales entitlement. kimi-k3 is not a live id — use kimi-k2.5.
BEDROCK_CHAT_MODELS: tuple[str, ...] = (
    "openai.gpt-6-luna",
    "openai.gpt-5.6-luna",
    "zai.glm-5",
    "moonshotai.kimi-k2.5",
    "deepseek.v3.2",
)

# Alias map for requested-but-unavailable ids.
BEDROCK_MODEL_ALIASES: dict[str, str] = {
    "moonshotai.kimi-k3": "moonshotai.kimi-k2.5",
}

BEDROCK_EMBED_MODELS: tuple[str, ...] = (
    "cohere.embed-v4:0",
    "amazon.titan-embed-text-v2:0",
)


def resolve_chat_model(model: str | None) -> str:
    raw = (model or settings.bedrock_model or "zai.glm-5").strip()
    return BEDROCK_MODEL_ALIASES.get(raw, raw)


def bedrock_token() -> str:
    return (
        (settings.aws_bearer_token_bedrock or "").strip()
        or os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    )


def bedrock_configured() -> bool:
    return bool(bedrock_token())


def bedrock_region() -> str:
    return (settings.bedrock_region or "us-east-1").strip()


def bedrock_embedding_region() -> str:
    return (
        (settings.bedrock_embedding_region or "").strip()
        or bedrock_region()
    )


def _auth_headers() -> dict[str, str]:
    token = bedrock_token()
    if not token:
        raise ValueError("AWS_BEARER_TOKEN_BEDROCK is not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _mantle_chat_url(model: str) -> str:
    """OpenAI-prefixed models use /openai/v1; others use Mantle /v1."""
    region = bedrock_region()
    if model.startswith("openai."):
        return f"https://bedrock-mantle.{region}.api.aws/openai/v1/chat/completions"
    return f"https://bedrock-mantle.{region}.api.aws/v1/chat/completions"


def _runtime_invoke_url(model_id: str, *, region: str | None = None) -> str:
    use_region = (region or bedrock_embedding_region()).strip()
    # Model IDs may contain ':' — path-encode for the invoke URL.
    encoded = model_id.replace(":", "%3A")
    return f"https://bedrock-runtime.{use_region}.amazonaws.com/model/{encoded}/invoke"


def chat_complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """OpenAI-compatible chat completions on bedrock-mantle.

    Returns a normalized dict: {content, tool_calls, model, raw}.
    """
    model_id = resolve_chat_model(model)
    url = _mantle_chat_url(model_id)
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
        resp = client.post(url, headers=_auth_headers(), json=body)
        if resp.status_code >= 400:
            logger.warning(
                "Bedrock chat error model=%s status=%s body=%s",
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


async def achat_complete(
    messages: list[dict[str, str]],
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
    url = _mantle_chat_url(model_id)
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
        resp = await client.post(url, headers=_auth_headers(), json=body)
        if resp.status_code >= 400:
            logger.warning(
                "Bedrock chat error model=%s status=%s body=%s",
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


def invoke_model(model_id: str, body: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
    """bedrock-runtime InvokeModel with bearer token."""
    url = _runtime_invoke_url(model_id)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=_auth_headers(), json=body)
        if resp.status_code >= 400:
            logger.warning(
                "Bedrock invoke error model=%s status=%s body=%s",
                model_id,
                resp.status_code,
                resp.text[:500],
            )
        resp.raise_for_status()
        return resp.json()


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    input_type: str = "search_document",
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed texts via Cohere Embed v4 or Titan Embed Text v2 on Bedrock."""
    if not texts:
        return []
    model_id = (model or settings.bedrock_embedding_model or BEDROCK_EMBED_MODELS[0]).strip()

    if model_id.startswith("cohere.embed"):
        payload: dict[str, Any] = {
            "texts": texts,
            "input_type": input_type,
            "embedding_types": ["float"],
        }
        data = invoke_model(model_id, payload)
        # Cohere returns embeddings / embeddings.float depending on API version
        floats = data.get("embeddings", {})
        if isinstance(floats, dict):
            vectors = floats.get("float") or floats.get("embeddings") or []
        elif isinstance(floats, list):
            vectors = floats
        else:
            vectors = data.get("embeddings") or []
        return [list(map(float, row)) for row in vectors]

    if model_id.startswith("amazon.titan-embed"):
        out: list[list[float]] = []
        dim = dimensions or settings.bedrock_embedding_dimensions or 1024
        for text in texts:
            titan_body: dict[str, Any] = {
                "inputText": text,
                "dimensions": dim,
                "normalize": True,
            }
            data = invoke_model(model_id, titan_body)
            vec = data.get("embedding") or []
            out.append([float(x) for x in vec])
        return out

    raise ValueError(f"Unsupported Bedrock embedding model: {model_id}")
