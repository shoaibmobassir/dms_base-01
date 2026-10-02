"""Deterministic binding labels (design doc §22.6).

Rules live in ``legal_systems.yaml`` (lawyer-reviewed). This module only
applies them: given an authority (and, for resolutions, the operative paragraph
cited) and the forum, it returns a label with the reason the lawyer will see.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG = Path(__file__).with_name("legal_systems.yaml")


@dataclass(frozen=True)
class BindingLabel:
    label: str
    reason: str

    @property
    def weight(self) -> float:
        return float(config()["labels"].get(self.label, 0.2))

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "reason": self.reason}


@dataclass(frozen=True)
class Forum:
    """Where the answer will be used. Built from the conversation's matter."""
    legal_system: str | None = None
    court: str | None = None
    matter_id: str | None = None


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    with _CONFIG.open() as fh:
        return yaml.safe_load(fh)


def forum_from_matter(matter: dict[str, Any] | None) -> Forum:
    if not matter:
        return Forum()
    juris = str(matter.get("jurisdiction") or "").lower()
    system = "international" if juris == "international" else "india" if juris == "india" else (juris or None)
    return Forum(legal_system=system, court=matter.get("court"), matter_id=matter.get("matter_id"))


def _india_court(name: str | None) -> str | None:
    n = (name or "").lower()
    for key, spec in config()["india"]["courts"].items():
        if any(alias.lower() in n for alias in spec["names"]):
            return key
    return None


def label_for(authority: dict[str, Any], forum: Forum | None = None, passage: dict[str, Any] | None = None) -> BindingLabel:
    """Label for ``authority`` (normalized dict from the provider) relative to ``forum``.

    ``passage`` is the cited passage (role, lead_verb) when known; for a resolution the
    label is per operative paragraph, so without a passage the label says so.
    """
    forum = forum or Forum()
    cfg = config()
    system = authority.get("legal_system")
    kind = authority.get("kind")

    if system == "international" and kind == "resolution":
        r = cfg["international"]["unsc"]
        reasons = r["reasons"]
        if passage is None:
            return BindingLabel("unknown", reasons["whole"])
        role = passage.get("role")
        if role == "headnote":
            return BindingLabel("not_binding", reasons["headnote"])
        if role == "preamble":
            return BindingLabel("not_binding", reasons["preamble"])
        verb = (passage.get("lead_verb") or "").lower()
        ch7 = bool(authority.get("chapter_vii"))
        if verb in r["binding_verbs"]:
            return BindingLabel("binding", reasons["decides_ch7"]) if ch7 else BindingLabel("likely_binding", reasons["decides"])
        if verb in r["likely_binding_verbs"]:
            return BindingLabel("likely_binding", reasons["demands_ch7"]) if ch7 else BindingLabel("unknown", reasons["demands"])
        if verb in r["permissive_verbs"]:
            return BindingLabel("not_binding", reasons["permissive"])
        if verb in r["recommendatory_verbs"]:
            return BindingLabel("recommendatory", reasons["recommendatory"])
        return BindingLabel("not_binding", reasons["other_operative"])

    if system == "international" and authority.get("provider_kind") == "pcij":
        p = cfg["international"]["pcij"]
        role = (passage or {}).get("role") or authority.get("role") or "majority"
        if role in p["opinion_roles"]:
            spec = p["opinion_roles"][role]
            return BindingLabel(spec["label"], spec["reason"])
        rules = p.get({"case": "judgment"}.get(kind, kind)) or p["order"]
        same = bool(forum.matter_id) and forum.matter_id == authority.get("matter_id")
        spec = rules.get("any") or (rules["same_case"] if same else rules["other"])
        return BindingLabel(spec["label"], spec["reason"])

    if system == "india":
        reasons = cfg["india"]["reasons"]
        if kind in ("statute", "regulation"):
            return BindingLabel("binding", reasons["statute"])
        src = _india_court((authority.get("court") or {}).get("name") if isinstance(authority.get("court"), dict) else authority.get("court"))
        dst = _india_court(forum.court)
        if src == "supreme_court":
            return BindingLabel("binding", reasons["supreme_court"])
        if src == "aptel" and dst in cfg["india"]["binding_on"]["aptel"]:
            return BindingLabel("binding", reasons["aptel_on_regulator"])
        if src and dst and src == dst:
            return BindingLabel("persuasive", reasons["same_level"])
        return BindingLabel("persuasive" if src else "unknown", reasons["other"])

    if forum.legal_system and system and forum.legal_system != system:
        return BindingLabel("persuasive", f"Authority from another legal system ({system}) than the forum's ({forum.legal_system}).")
    return BindingLabel("unknown", "No binding rule configured for this authority and forum.")
