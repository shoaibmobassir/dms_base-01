"""Citations rendered from authority metadata, never from model text (§22.8).

PDF page numbers from scanned reports are written "PDF p." so they are never
mistaken for the official report page.
"""
from __future__ import annotations

from datetime import date
from typing import Any

_KIND_LABEL = {"case": "Judgment", "advisory_opinion": "Advisory Opinion", "order": "Order"}
_ROLE_LABEL = {"dissent": "Dissenting Opinion", "separate_opinion": "Separate Opinion", "declaration": "Declaration"}


def judge_name(raw: str | None) -> str:
    """"MM. ANZILOTTI AND HUBER" -> "MM. Anzilotti and Huber"; "SIR CECIL HURST" -> "Sir Cecil Hurst"."""
    words = []
    for w in (raw or "").split():
        up = w.upper()
        if up in ("M.", "MM."):
            words.append("M." if up == "M." else "MM.")
        elif up == "AND":
            words.append("and")
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def _long_date(value: Any) -> str:
    if isinstance(value, date):
        return f"{value.day} {value:%B %Y}"
    if isinstance(value, str) and len(value) >= 10:
        try:
            return _long_date(date.fromisoformat(value[:10]))
        except ValueError:
            return value
    return str(value or "")


def format_citation(authority: dict[str, Any], *, page: int | None = None, para: int | str | None = None,
                    page_kind: str = "pdf") -> str:
    kind = authority.get("provider_kind")
    cit = authority.get("citation") or {}
    if kind == "pcij":
        series = cit.get("series")
        parts = [f"*{authority.get('case_name') or authority.get('title')}*", _KIND_LABEL.get(authority.get("kind"), "Decision"),
                 _long_date(authority.get("decision_date")), "P.C.I.J.", f"Series {series}", f"No. {cit.get('number')}"]
        out = ", ".join(p for p in parts if p and "None" not in p)
        role = authority.get("role")
        if role in _ROLE_LABEL:
            judge = authority.get("judge")
            out += f" ({_ROLE_LABEL[role]}{' of ' + judge_name(judge) if judge else ''})"
        if page:
            out += f", {'p.' if page_kind == 'official' else 'PDF p.'} {page}"
        return out
    if kind == "unsc":
        out = f"S/RES/{cit.get('number')} ({cit.get('year')}), {_long_date(authority.get('decision_date'))}"
        if para:
            out += f", para. {para}" if str(para).isdigit() else f", operative paragraph ({para})"
        return out
    return str(cit.get("primary") or authority.get("title") or authority.get("authority_id"))
