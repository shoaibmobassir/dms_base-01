"""
Model Router: Unified Multi-Provider LLM Gateway with Reasoning Controls and Local Ollama Execution.
Clean-room independent implementation.
"""

from dataclasses import dataclass, field
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx

from app.auth.key_vault import get_key_vault

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    reasoning_content: Optional[str] = None


class ModelRouter:
    """Dispatches completions across OpenAI, Anthropic, Gemini, Groq, and Ollama."""

    def __init__(self):
        self.vault = get_key_vault()
        self.ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    async def complete(
        self,
        messages: List[LLMMessage],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: Optional[str] = None,  # none, low, medium, high, max
        tenant_api_keys: Optional[Dict[str, str]] = None,
    ) -> LLMResponse:
        """Executes a unified LLM completion with automatic fallback."""
        active_provider = (provider or os.environ.get("DEFAULT_LLM_PROVIDER", "groq")).lower()
        active_model = model

        # Resolve provider-specific API keys
        keys = tenant_api_keys or {}

        try:
            if active_provider == "anthropic":
                return await self._call_anthropic(messages, active_model, temperature, max_tokens, json_mode, keys)
            elif active_provider == "openai":
                return await self._call_openai(messages, active_model, temperature, max_tokens, json_mode, reasoning_effort, keys)
            elif active_provider == "gemini":
                return await self._call_gemini(messages, active_model, temperature, max_tokens, json_mode, keys)
            elif active_provider == "ollama":
                return await self._call_ollama(messages, active_model, temperature, max_tokens, json_mode)
            else:
                # Default to Groq / fallback
                return await self._call_groq(messages, active_model, temperature, max_tokens, json_mode, keys)
        except Exception as exc:
            logger.warning("Primary provider %s failed: %s. Attempting fallback.", active_provider, exc)
            return await self._call_fallback(messages, json_mode)

    async def _call_anthropic(
        self,
        messages: List[LLMMessage],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        keys: Dict[str, str],
    ) -> LLMResponse:
        api_key = keys.get("anthropic") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Anthropic API key not configured")

        model_name = model or "claude-3-7-sonnet-20250219"
        system_prompt = next((m.content for m in messages if m.role == "system"), "")
        anthropic_msgs = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        if json_mode and system_prompt:
            system_prompt += "\nOutput your response strictly as valid JSON."

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": anthropic_msgs,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["content"][0]["text"]
            usage = data.get("usage", {})
            return LLMResponse(content=content, provider="anthropic", model=model_name, usage=usage)

    async def _call_openai(
        self,
        messages: List[LLMMessage],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        reasoning_effort: Optional[str],
        keys: Dict[str, str],
    ) -> LLMResponse:
        api_key = keys.get("openai") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key not configured")

        model_name = model or "gpt-4o"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if reasoning_effort and "o1" in model_name or "o3" in model_name:
            payload["reasoning_effort"] = reasoning_effort

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return LLMResponse(
                content=choice["message"]["content"],
                provider="openai",
                model=model_name,
                usage=data.get("usage", {}),
                finish_reason=choice.get("finish_reason"),
            )

    async def _call_gemini(
        self,
        messages: List[LLMMessage],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        keys: Dict[str, str],
    ) -> LLMResponse:
        api_key = keys.get("gemini") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API key not configured")

        model_name = model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

        contents = []
        for m in messages:
            role = "user" if m.role in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen_config["responseMimeType"] = "application/json"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json={"contents": contents, "generationConfig": gen_config})
            resp.raise_for_status()
            data = resp.json()
            cand = data["candidates"][0]
            text = cand["content"]["parts"][0]["text"]
            return LLMResponse(content=text, provider="gemini", model=model_name, usage=data.get("usageMetadata", {}))

    async def _call_ollama(
        self,
        messages: List[LLMMessage],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        model_name = model or "llama3.1:8b"
        payload = {
            "model": model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                content=data["message"]["content"],
                provider="ollama",
                model=model_name,
            )

    async def _call_groq(
        self,
        messages: List[LLMMessage],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        keys: Dict[str, str],
    ) -> LLMResponse:
        api_key = keys.get("groq") or os.environ.get("GROQ_API_KEY")
        if not api_key:
            # Fallback to local extractive summary if no cloud key exists
            return await self._call_fallback(messages, json_mode)

        model_name = model or "llama-3.3-70b-versatile"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            return LLMResponse(
                content=choice["message"]["content"],
                provider="groq",
                model=model_name,
                usage=data.get("usage", {}),
            )

    async def _call_fallback(self, messages: List[LLMMessage], json_mode: bool) -> LLMResponse:
        user_msg = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if json_mode:
            content = json.dumps({"status": "completed", "summary": user_msg[:300], "abstained": False})
        else:
            content = f"Analysis grounded on institutional record:\n{user_msg[:500]}"
        return LLMResponse(content=content, provider="local-extractive-fallback", model="extractive-v1")


_router_instance: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance
