"""A conversation as a Word document: who said what and when, with each answer's sources under it."""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

from docx import Document
from docx.shared import Pt


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _stamp(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    return value.strftime("%d %b %Y, %H:%M")


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _add_text(doc, text: str) -> None:
    """Paragraphs, bullets and numbered lines of the answer; **bold** kept, other Markdown marks dropped."""
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        style = None
        heading = re.match(r"^#{1,4}\s+(.*)$", line)
        if heading:
            doc.add_heading(heading.group(1), level=3)
            continue
        if re.match(r"^[-*•]\s+", line):
            line, style = re.sub(r"^[-*•]\s+", "", line), "List Bullet"
        elif re.match(r"^\d+[.)]\s+", line):
            line, style = re.sub(r"^\d+[.)]\s+", "", line), "List Number"
        para = doc.add_paragraph(style=style)
        pos = 0
        for m in _BOLD.finditer(line):
            para.add_run(line[pos:m.start()])
            para.add_run(m.group(1)).bold = True
            pos = m.end()
        para.add_run(line[pos:])


def conversation_to_docx(title: str, messages: list[Any]) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading(title or "Conversation", level=1)
    for m in messages:
        role = str(_get(m, "role", ""))
        content = str(_get(m, "content", "") or "").strip()
        if role == "system" or not content:
            continue
        who = "You" if role == "user" else "Assistant"
        when = _stamp(_get(m, "created_at"))
        doc.add_heading(f"{who}{f' ({when})' if when else ''}", level=2)
        _add_text(doc, content)
        cites = _get(m, "citations") or []
        if role == "assistant" and cites:
            doc.add_paragraph().add_run("Sources").bold = True
            for c in cites:
                ref = _get(c, "ref", "")
                name = _get(c, "title") or _get(c, "document_id") or "Document"
                page = _get(c, "page")
                doc.add_paragraph(f"[{ref}] {name}{f', p. {page}' if page not in (None, '') else ''}", style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
