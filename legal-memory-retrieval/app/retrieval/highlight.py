from __future__ import annotations

import re
import html

_STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after", "above", "below",
    "to", "from", "up", "down", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "and", "but", "if", "or", "because",
    "as", "until", "while", "of", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "it", "its", "we", "our", "you", "your", "they", "them",
    "matter", "document", "documents", "firm", "legal", "clause", "clauses"
}


def extract_keywords(query: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z0-9_\-\.]{3,}\b", query or "")
    keywords: list[str] = []
    for w in words:
        low = w.lower()
        if low not in _STOP_WORDS and low not in [k.lower() for k in keywords]:
            keywords.append(w)
    return keywords


def highlight_snippet(text: str, query: str, max_chars: int = 350) -> str:
    """Highlight keywords in a snippet for search hit cards."""
    if not text:
        return ""
    clean_text = " ".join(text.split())
    keywords = extract_keywords(query)
    
    if not keywords:
        snippet = clean_text[:max_chars]
        if len(clean_text) > max_chars:
            snippet += "..."
        return html.escape(snippet)

    # Find the best window with highest keyword density
    pattern = re.compile(r"(" + "|".join(re.escape(k) for k in keywords) + r")", re.IGNORECASE)
    matches = list(pattern.finditer(clean_text))
    
    if not matches:
        snippet = clean_text[:max_chars]
        if len(clean_text) > max_chars:
            snippet += "..."
        return html.escape(snippet)

    first_match = matches[0]
    start_pos = max(0, first_match.start() - 60)
    end_pos = min(len(clean_text), start_pos + max_chars)
    
    # Adjust to word boundaries
    if start_pos > 0:
        sp = clean_text.find(" ", start_pos)
        if sp != -1 and sp < first_match.start():
            start_pos = sp + 1
    if end_pos < len(clean_text):
        ep = clean_text.rfind(" ", start_pos, end_pos)
        if ep != -1:
            end_pos = ep

    window = clean_text[start_pos:end_pos]
    if start_pos > 0:
        window = "..." + window
    if end_pos < len(clean_text):
        window = window + "..."

    # Apply highlight markup
    def _repl(m):
        return f'<mark class="dms-source-highlight">{html.escape(m.group(0))}</mark>'

    highlighted = pattern.sub(_repl, html.escape(window))
    return highlighted


def highlight_document_body(body: str, query: str = "", chunk_text: str = "") -> tuple[str, int]:
    """Highlight matching chunk or keywords in full document body for Document Viewer."""
    if not body:
        return "", 0

    clean_body = body
    match_count = 0

    # If specific chunk text is provided, highlight that exact chunk in the document body
    if chunk_text and len(chunk_text.strip()) > 20:
        chunk_clean = chunk_text.strip()
        # Find position of chunk text or sub-phrase
        pos = clean_body.find(chunk_clean[:80])
        if pos != -1:
            end_pos = clean_body.find(chunk_clean[-60:], pos)
            if end_pos != -1:
                end_pos += len(chunk_clean[-60:])
            else:
                end_pos = min(len(clean_body), pos + len(chunk_clean))
            
            before = html.escape(clean_body[:pos])
            target = html.escape(clean_body[pos:end_pos])
            after = html.escape(clean_body[end_pos:])
            
            highlighted = f'{before}<mark id="match-1" class="dms-source-highlight dms-chunk-target">{target}</mark>{after}'
            return highlighted, 1

    # Fallback to keyword matching in document
    keywords = extract_keywords(query)
    if not keywords:
        return html.escape(clean_body), 0

    pattern = re.compile(r"(" + "|".join(re.escape(k) for k in keywords) + r")", re.IGNORECASE)
    
    matches = list(pattern.finditer(clean_body))
    match_count = len(matches)

    def _repl(m):
        return f'<mark class="dms-source-highlight">{html.escape(m.group(0))}</mark>'

    highlighted = pattern.sub(_repl, html.escape(clean_body))
    return highlighted, match_count
