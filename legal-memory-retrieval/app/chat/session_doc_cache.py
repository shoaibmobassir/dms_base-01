"""Process-local document text cache, isolated by member and version.

A later version of the same document replaces earlier versions for that
member. Text is never readable under a different member id.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

_MAX_ENTRIES = 128
_UNREADABLE = "Document could not be read."

_lock = threading.Lock()
_texts: OrderedDict[tuple[str, str, str], str] = OrderedDict()


def _key(member_id: str, document_id: str, version_id: str) -> tuple[str, str, str]:
    return (member_id, document_id, version_id)


def get(member_id: str | None, document_id: str | None, version_id: str | None) -> str | None:
    """Return cached text, or None if the member/version key is absent."""
    if not member_id or not document_id or not version_id:
        return None
    key = _key(member_id, document_id, version_id)
    with _lock:
        text = _texts.get(key)
        if text is None:
            return None
        _texts.move_to_end(key)
        return text


def put(
    member_id: str | None,
    document_id: str | None,
    version_id: str | None,
    text: str,
) -> None:
    """Store text for one member and version. Drop other versions of that document."""
    if not member_id or not document_id or not version_id:
        return
    if not text or text == _UNREADABLE:
        return
    key = _key(member_id, document_id, version_id)
    with _lock:
        stale = [
            existing
            for existing in _texts
            if existing[0] == member_id and existing[1] == document_id and existing[2] != version_id
        ]
        for existing in stale:
            del _texts[existing]
        _texts[key] = text
        _texts.move_to_end(key)
        while len(_texts) > _MAX_ENTRIES:
            _texts.popitem(last=False)


def reset() -> None:
    """Clear the cache. Used by tests."""
    with _lock:
        _texts.clear()
