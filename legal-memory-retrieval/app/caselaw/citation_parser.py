"""
Citation Parser: Regex-based Legal Citation Tokenizer and Normalizer.
Clean-room independent implementation.
"""

from dataclasses import dataclass
import re
from typing import List, Optional


@dataclass
class LegalCitation:
    raw_citation: str
    normalized_citation: str
    volume: Optional[int] = None
    reporter: Optional[str] = None
    page: Optional[int] = None
    citation_type: str = "case_law"  # case_law | statute | regulation


class CitationParser:
    """Extracts and normalizes legal citations from legal briefs and contracts."""

    CASE_RE = re.compile(
        r"\b(\d+)\s+((?:[A-Za-z0-9\.\s]*?\s+)?(?:U\.S\.|F\.\d*d|F\.4th|F\.3d|F\.2d|F\.\s*Supp\.\s*\d*d?|S\.\s*Ct\.|L\.\s*Ed\.\s*\d*d?|A\.\d*d?|P\.\d*d?|N\.E\.\d*d?|N\.W\.\d*d?|S\.E\.\d*d?|S\.W\.\d*d?|So\.\d*d?|F\.))\s+(\d+)\b",
        re.IGNORECASE,
    )


    # Pattern for Statutory Citations (e.g. 42 U.S.C. § 1983, 11 U.S.C. 547)
    STATUTE_RE = re.compile(
        r"\b(\d+)\s+U\.S\.C\.(?:\s+§+)?\s+(\d+(?:[a-zA-Z0-9\-\(\)]*))\b",
        re.IGNORECASE,
    )

    def extract_citations(self, text: str) -> List[LegalCitation]:
        citations: List[LegalCitation] = []
        seen = set()

        # Case law citations
        for match in self.CASE_RE.finditer(text):
            raw = match.group(0).strip()
            if raw in seen:
                continue
            seen.add(raw)
            try:
                vol = int(match.group(1))
                rep = match.group(2).strip()
                pg = int(match.group(3))
                normalized = f"{vol} {rep} {pg}"
                citations.append(
                    LegalCitation(
                        raw_citation=raw,
                        normalized_citation=normalized,
                        volume=vol,
                        reporter=rep,
                        page=pg,
                        citation_type="case_law",
                    )
                )
            except Exception:
                citations.append(LegalCitation(raw_citation=raw, normalized_citation=raw))

        # Statutes
        for match in self.STATUTE_RE.finditer(text):
            raw = match.group(0).strip()
            if raw in seen:
                continue
            seen.add(raw)
            title_num = int(match.group(1))
            sec = match.group(2)
            normalized = f"{title_num} U.S.C. § {sec}"
            citations.append(
                LegalCitation(
                    raw_citation=raw,
                    normalized_citation=normalized,
                    volume=title_num,
                    reporter="U.S.C.",
                    page=None,
                    citation_type="statute",
                )
            )

        return citations


_parser_instance: Optional[CitationParser] = None


def get_citation_parser() -> CitationParser:
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = CitationParser()
    return _parser_instance
