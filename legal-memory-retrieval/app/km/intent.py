"""What kind of KM question is this? Cheap regex classification.

A question may carry several needs at once ("who is on the Acme deal and
what is the long stop date?"), so this returns flags, not a single label.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_PEOPLE_RE = re.compile(
    r"\bwho\b[^?]{0,40}\b(work|working|worked|staff|staffed|lead|leads|led|leading|handl|responsible|"
    r"in the firm|at the firm|in our firm|on the team|on this|expert|specialis|specializ|sits|based)"
    r"|\bwhich (partner|associate|counsel|lawyer|member|attorney|colleague|paralegal|junior|person|people)s?\b"
    r"|\b(our|the|matter|deal) team\b|\bteam members?\b|\bstaffed\b|\bexperts? (in|on)\b"
    r"|\bspeciali[sz](e|es|ed|ing|ation|ist)\b|\bknowledge manager\b|\bpoint of contact\b",
    re.I,
)
_OVERVIEW_RE = re.compile(
    r"^\s*(please\s+)?(explain|summari[sz]e|overview|describe|brief me|walk me through|tell me about|"
    r"what is this|what's this|what is going on|status|give me (an|a) (overview|summary|brief))\b",
    re.I,
)
_LIST_RE = re.compile(
    r"\b(which|what|list|all|any)\b[^?]{0,20}\b(matters|cases|deals|mandates|transactions|work|engagements|"
    r"disputes|arbitrations|proceedings)\b"
    r"|\bhave we (done|handled|acted|advised|worked)\b|\bwork (we have|we've) done\b|\bmatters? (involv|for|with)\b",
    re.I,
)


@dataclass
class KMIntent:
    people: bool = False
    overview: bool = False
    matter_list: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def classify(question: str, *, scoped: bool = False) -> KMIntent:
    q = (question or "").strip()
    words = len(q.split())
    overview = bool(_OVERVIEW_RE.search(q)) or (scoped and words <= 3)
    return KMIntent(
        people=bool(_PEOPLE_RE.search(q)),
        overview=overview,
        matter_list=bool(_LIST_RE.search(q)),
    )
