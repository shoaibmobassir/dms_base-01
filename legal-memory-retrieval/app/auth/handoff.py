"""
Auth Handoff: Secure One-Time Ticket Exchange for Microsoft Word Taskpane and External Tools.
Clean-room independent implementation.
"""

from datetime import datetime, timedelta
import secrets
from typing import Dict, Optional


class AuthHandoffService:
    """Manages short-lived one-time tickets for secure Word taskpane authentication."""

    def __init__(self, ticket_ttl_seconds: int = 300):
        self.ttl = ticket_ttl_seconds
        # In-memory ticket cache with timestamps (backed by Redis when available)
        self._tickets: Dict[str, Dict[str, str]] = {}

    def create_ticket(self, member_id: str, email: Optional[str] = None) -> str:
        """Generates a cryptographically random one-time ticket."""
        ticket = f"TKT-{secrets.token_urlsafe(32)}"
        expiry = datetime.utcnow() + timedelta(seconds=self.ttl)
        self._tickets[ticket] = {
            "member_id": member_id,
            "email": email or "",
            "expires_at": expiry.isoformat(),
        }
        return ticket

    def exchange_ticket(self, ticket: str) -> Optional[Dict[str, str]]:
        """Exchanges a one-time ticket for member identity and invalidates it immediately."""
        self._cleanup_expired()
        record = self._tickets.pop(ticket, None)
        if not record:
            return None

        expires_at = datetime.fromisoformat(record["expires_at"])
        if datetime.utcnow() > expires_at:
            return None

        return {
            "member_id": record["member_id"],
            "email": record["email"],
            "session_token": f"SES-{secrets.token_urlsafe(32)}",
        }

    def _cleanup_expired(self):
        now = datetime.utcnow()
        expired_keys = [
            k for k, v in self._tickets.items()
            if now > datetime.fromisoformat(v["expires_at"])
        ]
        for k in expired_keys:
            self._tickets.pop(k, None)


_handoff_service: Optional[AuthHandoffService] = None


def get_auth_handoff_service() -> AuthHandoffService:
    global _handoff_service
    if _handoff_service is None:
        _handoff_service = AuthHandoffService()
    return _handoff_service
