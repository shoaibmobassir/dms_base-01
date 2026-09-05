"""Review Planner for legal due diligence and multi-document review.

Decomposes broad review goals into structured feature extraction queries,
clause filters, and risk thresholds.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional


@dataclass
class ReviewFeature:
    feature_id: str
    name: str
    category: str
    search_keywords: List[str]
    sample_queries: List[str]
    severity_default: str  # critical | high | medium | low
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FEATURE_CATALOG: dict[str, ReviewFeature] = {
    "indemnity": ReviewFeature(
        feature_id="indemnity",
        name="Indemnification & Hold Harmless",
        category="indemnity",
        search_keywords=["indemnify", "indemnification", "hold harmless", "defend", "tax indemnity"],
        sample_queries=["indemnification obligations and tax indemnity caps", "seller indemnity liability"],
        severity_default="high",
        description="Scans for seller/buyer indemnification obligations, caps, baskets, and exclusions.",
    ),
    "liability": ReviewFeature(
        feature_id="liability",
        name="Limitation of Liability & Caps",
        category="liability",
        search_keywords=["aggregate liability", "consequential damages", "liability cap", "limitation of liability"],
        sample_queries=["aggregate liability limitation and damages exclusion", "maximum liability cap"],
        severity_default="critical",
        description="Identifies aggregate liability caps, super-caps, and exclusion of consequential damages.",
    ),
    "change_of_control": ReviewFeature(
        feature_id="change_of_control",
        name="Change of Control & Assignment",
        category="change_of_control",
        search_keywords=["change of control", "assignment", "successor", "merger", "consolidation"],
        sample_queries=["change of control consent requirements", "anti-assignment and successor clauses"],
        severity_default="high",
        description="Flags restrictions on transfer, assignment, or ownership changes requiring consent.",
    ),
    "termination": ReviewFeature(
        feature_id="termination",
        name="Termination Rights & Cure Periods",
        category="termination",
        search_keywords=["termination", "cure period", "material breach", "immediate termination", "convenience"],
        sample_queries=["termination for convenience or cause and notice period", "cure period on default"],
        severity_default="medium",
        description="Analyzes termination triggers, notice periods, and termination fees.",
    ),
    "governing_law": ReviewFeature(
        feature_id="governing_law",
        name="Governing Law & Dispute Resolution",
        category="governing_law",
        search_keywords=["governing law", "jurisdiction", "arbitration", "exclusive venue", "courts of"],
        sample_queries=["governing law jurisdiction and arbitration clause", "venue of dispute resolution"],
        severity_default="medium",
        description="Checks governing jurisdiction, court venue, and binding arbitration provisions.",
    ),
    "non_compete": ReviewFeature(
        feature_id="non_compete",
        name="Non-Compete & Restrictive Covenants",
        category="compliance",
        search_keywords=["non-compete", "non-solicitation", "restrictive covenant", "restraint of trade"],
        sample_queries=["non-compete duration and non-solicitation of employees", "scope of restrictive covenant"],
        severity_default="high",
        description="Detects geographic and temporal non-compete and non-solicitation restraints.",
    ),
    "confidentiality": ReviewFeature(
        feature_id="confidentiality",
        name="Confidentiality & Data Protection",
        category="compliance",
        search_keywords=["confidential information", "non-disclosure", "trade secret", "data protection"],
        sample_queries=["confidentiality duration and permitted disclosures", "return or destruction of confidential info"],
        severity_default="low",
        description="Evaluates definition of confidential information and survival terms.",
    ),
}


@dataclass
class ReviewPlan:
    plan_id: str
    target_matter_id: Optional[str]
    features: List[ReviewFeature]
    keywords_filter: List[str]
    max_candidates_per_doc: int = 5
    concurrency_limit: int = 20

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "target_matter_id": self.target_matter_id,
            "features": [f.to_dict() for f in self.features],
            "keywords_filter": self.keywords_filter,
            "max_candidates_per_doc": self.max_candidates_per_doc,
            "concurrency_limit": self.concurrency_limit,
        }


def build_review_plan(
    requested_features: Optional[List[str]] = None,
    query_text: Optional[str] = None,
    matter_id: Optional[str] = None,
) -> ReviewPlan:
    """Construct an execution plan for a document review run."""
    selected_features: List[ReviewFeature] = []

    if requested_features:
        for f in requested_features:
            norm = f.strip().lower().replace(" ", "_")
            if norm in FEATURE_CATALOG:
                selected_features.append(FEATURE_CATALOG[norm])
    elif query_text:
        lower = query_text.lower()
        for key, feat in FEATURE_CATALOG.items():
            if key in lower or any(kw in lower for kw in feat.search_keywords):
                selected_features.append(feat)

    if not selected_features:
        # Default full due diligence review features
        selected_features = [
            FEATURE_CATALOG["indemnity"],
            FEATURE_CATALOG["liability"],
            FEATURE_CATALOG["change_of_control"],
            FEATURE_CATALOG["termination"],
            FEATURE_CATALOG["governing_law"],
        ]

    all_kws = list(dict.fromkeys([kw for feat in selected_features for kw in feat.search_keywords]))
    import uuid
    return ReviewPlan(
        plan_id=f"PLAN-{uuid.uuid4().hex[:8].upper()}",
        target_matter_id=matter_id,
        features=selected_features,
        keywords_filter=all_kws,
    )
