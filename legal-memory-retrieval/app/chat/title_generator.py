"""
Chat title generator: Auto-generate a concise chat title from the first
user message using a lightweight LLM call, with fallback to truncation.
Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_TITLE_PROMPT = """\
Generate a short, descriptive title (5-8 words maximum) for a legal assistant \
chat session that starts with the following user message. Return ONLY the title \
text, nothing else. No quotes, no punctuation at the end.

User message:
{message}
"""

MAX_FALLBACK_LENGTH = 120


def generate_chat_title(message: str) -> str:
    """
    Generate a concise chat title from the first user message.
    Tries an LLM call first, falls back to truncation.
    """
    if not message or not message.strip():
        return "New Chat"

    # Try LLM-generated title
    try:
        title = _llm_title(message)
        if title and len(title) <= 80:
            return title
    except Exception as exc:
        logger.warning("[title-gen] LLM title generation failed: %s", exc)

    # Fallback: truncate the user message
    clean = message.strip().replace("\n", " ")
    if len(clean) > MAX_FALLBACK_LENGTH:
        return clean[:MAX_FALLBACK_LENGTH].rsplit(" ", 1)[0] + "…"
    return clean


def _llm_title(message: str) -> str:
    """Call the LLM to generate a title."""
    import httpx

    prompt = _TITLE_PROMPT.format(message=message[:500])

    if settings.gemini_api_key:
        model = "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 30},
        }
        resp = httpx.post(url, json=body, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "").strip().strip('"').strip("'")

    if settings.groq_api_key:
        model_id = "llama3-8b-8192"
        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 30,
        }
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip().strip('"').strip("'")

    return ""
