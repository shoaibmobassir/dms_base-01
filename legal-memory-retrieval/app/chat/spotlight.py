"""
Prompt injection protection: Nonce-fenced spotlighting for untrusted content.
Clean-room independent implementation for FirmOS legal assistant chatbot.

All user-uploaded document content, filenames, and workflow bodies are wrapped
in nonce-fenced tags that the LLM is instructed to treat as DATA only, never
as instructions. The nonce is random per request so injected content cannot
forge a matching closing tag to escape the fence.
"""

from __future__ import annotations

import os
import re


def generate_nonce() -> str:
    """Generate a random 16-byte hex nonce for per-request fence tokens."""
    return os.urandom(16).hex()


_FENCE_TAG_RE = re.compile(
    r"<(/?)(untrusted-content|workflow-instructions)", re.IGNORECASE
)


def _neutralize_fence_tokens(text: str, nonce: str) -> str:
    """
    Strip any echoed nonce and HTML-encode the '<' of any literal fence tag
    inside fenced content, so even if the model echoes the content it never
    sees a clean boundary token inside the data.
    """
    sanitised = text.replace(nonce, "[redacted-nonce]")
    return _FENCE_TAG_RE.sub(r"&lt;\1\2", sanitised)


def spotlight(text: str, nonce: str) -> str:
    """
    Wrap untrusted user-controlled text in a nonce-fenced tag.
    The LLM is instructed (in the system prompt) to treat everything inside
    these tags as data, not as instructions — a technique called "spotlighting".
    """
    neutralised = _neutralize_fence_tokens(text, nonce)
    return (
        f'<untrusted-content nonce="{nonce}">\n'
        f"{neutralised}\n"
        f'</untrusted-content nonce="{nonce}">'
    )


def spotlight_workflow(text: str, nonce: str) -> str:
    """
    Wrap a user-installed workflow body in the semi-trusted
    <workflow-instructions> fence. Unlike document content, workflows
    ARE meant to be followed — but they cannot override system rules,
    exfiltrate data, or re-interpret other fenced content.
    """
    neutralised = _neutralize_fence_tokens(text, nonce)
    return (
        f'<workflow-instructions nonce="{nonce}">\n'
        f"{neutralised}\n"
        f'</workflow-instructions nonce="{nonce}">'
    )


def spotlight_filename(filename: str, nonce: str | None = None) -> str:
    """Fence a user-controlled filename when spotlighting is enabled."""
    if nonce:
        return spotlight(filename, nonce)
    return filename
