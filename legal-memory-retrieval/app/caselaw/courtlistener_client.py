"""
CourtListener Client: Async Client for Case Law Verification and Judicial Opinion Retrieval.
Clean-room independent implementation.

A lookup that fails (no network, no token, HTTP error, no match) is reported as
not verified. It never produces a resolved opinion. CourtListener has no
treatment (citator) data, so treatment status is always ``unknown``.
"""

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger(__name__)

# resolution values
RESOLVED = "resolved"
NOT_FOUND = "not_found"
PROVIDER_ERROR = "provider_error"


@dataclass
class VerifiedOpinion:
    citation: str
    resolution: str  # resolved | not_found | provider_error
    case_name: Optional[str] = None
    court: Optional[str] = None
    date_filed: Optional[str] = None
    precedential_status: Optional[str] = None  # as published by CourtListener; not treatment
    summary: str = ""
    courtlistener_url: Optional[str] = None
    status: Dict[str, Any] = field(default_factory=lambda: {"signal": "unknown", "source": "none"})
    reason: Optional[str] = None

    @property
    def verified(self) -> bool:
        return self.resolution == RESOLVED


class CourtListenerClient:
    """Queries CourtListener REST API v4 with local caching to verify legal citations."""

    def __init__(self, api_token: Optional[str] = None):
        self.token = api_token or os.environ.get("COURTLISTENER_API_KEY")
        self.base_url = "https://www.courtlistener.com/api/rest/v4"
        self._cache: Dict[str, VerifiedOpinion] = {}

    async def verify_citation(self, citation_str: str) -> VerifiedOpinion:
        norm = citation_str.strip()
        if norm in self._cache:
            return self._cache[norm]

        headers = {}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        params = {"q": f'"{norm}"', "type": "o", "format": "json"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{self.base_url}/search/", params=params, headers=headers)
        except Exception as exc:
            logger.warning("CourtListener lookup failed for citation %s: %s", norm, exc)
            # Not cached: a transient failure must not stick.
            return VerifiedOpinion(citation=norm, resolution=PROVIDER_ERROR, reason="CourtListener could not be reached")

        if resp.status_code != 200:
            return VerifiedOpinion(citation=norm, resolution=PROVIDER_ERROR, reason=f"CourtListener returned HTTP {resp.status_code}")

        results = (resp.json() or {}).get("results") or []
        if not results:
            opinion = VerifiedOpinion(citation=norm, resolution=NOT_FOUND, reason="No opinion matches this citation")
        else:
            top = results[0]
            opinion = VerifiedOpinion(
                citation=norm,
                resolution=RESOLVED,
                case_name=top.get("caseName"),
                court=top.get("court"),
                date_filed=top.get("dateFiled"),
                precedential_status=top.get("status"),
                summary=(top.get("snippet") or "")[:300],
                courtlistener_url=f"https://www.courtlistener.com{top.get('absolute_url', '')}" if top.get("absolute_url") else None,
                reason="Treatment not checked: CourtListener has no citator data",
            )
        self._cache[norm] = opinion
        return opinion


_courtlistener_client: Optional[CourtListenerClient] = None


def get_courtlistener_client() -> CourtListenerClient:
    global _courtlistener_client
    if _courtlistener_client is None:
        _courtlistener_client = CourtListenerClient()
    return _courtlistener_client
