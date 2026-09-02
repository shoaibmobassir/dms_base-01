"""Text chunking for legal documents.

Reasoning:
  Legal paragraphs are typically long (500-1500 chars) and contain complete
  arguments that shouldn't be split mid-sentence. We use larger chunks (1200)
  with more overlap (150) than the original (900/90) to preserve argument
  coherence. We also prefer splitting on paragraph boundaries (\\n\\n) before
  falling back to single newlines.
"""
from __future__ import annotations


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            # Prefer paragraph boundary first
            cut = text.rfind("\n\n", start, end)
            if cut > start + max_chars // 2:
                end = cut
            else:
                # Fall back to single newline
                cut = text.rfind("\n", start, end)
                if cut > start + max_chars // 2:
                    end = cut
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return parts
