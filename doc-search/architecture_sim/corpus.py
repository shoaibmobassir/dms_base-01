"""Synthetic legal corpus generator — simulates 100s of multi-page contracts."""
from __future__ import annotations

import random
from dataclasses import dataclass

# Clause templates used for hierarchical structure + review features
CLAUSE_TEMPLATES: dict[str, list[str]] = {
    "indemnification": [
        "Seller shall indemnify Buyer against Losses arising from Tax Claims, subject to an aggregate cap of {cap}.",
        "The indemnity obligations under this Section shall survive Closing for a period of {years} years.",
        "Buyer shall not be entitled to indemnification unless Losses exceed a deductible of {deductible}.",
    ],
    "change_of_control": [
        "Neither Party may assign this Agreement upon a Change of Control without prior written consent of the other Party.",
        "A Change of Control of Seller shall constitute an Event of Default unless Buyer consents in writing.",
        "Change of Control means any transaction resulting in transfer of more than fifty percent (50%) of voting securities.",
    ],
    "termination": [
        "Either Party may terminate this Agreement upon {days} days' prior written notice.",
        "Buyer may terminate if Closing has not occurred by the Outside Date of {date}.",
        "Termination for convenience is not permitted except as expressly set forth herein.",
    ],
    "liability": [
        "The aggregate liability of the Seller under this Agreement shall not exceed {cap}.",
        "Neither Party shall be liable for consequential, incidental, or punitive damages.",
        "Liability caps shall not apply to fraud, willful misconduct, or breaches of Fundamental Representations.",
    ],
    "governing_law": [
        "This Agreement shall be governed by the laws of the State of {jurisdiction}.",
        "Disputes shall be resolved exclusively in the courts of {jurisdiction}.",
    ],
    "assignment": [
        "This Agreement may not be assigned without the prior written consent of the other Party.",
        "Seller may assign to an Affiliate without consent, provided Seller remains liable.",
    ],
    "non_compete": [
        "Seller agrees not to compete in the Territory for a period of {years} years following Closing.",
        "Non-compete restrictions shall be geographically limited to {territory}.",
    ],
    "unusual_obligations": [
        "Seller shall maintain a minimum cash balance of {cap} through the first anniversary of Closing.",
        "Buyer shall grant Seller a right of first refusal on any subsequent equity issuance.",
    ],
}

SECTION_ORDER = [
    ("1", "Definitions"),
    ("2", "Sale and Purchase"),
    ("3", "Representations and Warranties"),
    ("4", "Covenants"),
    ("5", "Change of Control"),
    ("6", "Termination"),
    ("7", "Assignment"),
    ("8", "Indemnification"),
    ("9", "Limitation of Liability"),
    ("10", "Non-Compete"),
    ("11", "Governing Law"),
    ("12", "Miscellaneous"),
]

CAPS = ["$50,000", "$75,000", "$100,000", "$250,000", "$1,000,000"]
JURISDICTIONS = ["New York", "Delaware", "England and Wales", "Singapore", "California"]
TERRITORIES = ["North America", "the European Union", "Asia-Pacific", "India"]


@dataclass
class SyntheticFile:
    relative_path: str  # preserves folder hierarchy
    name: str
    document_type: str
    matter_name: str
    client_name: str
    pages: int
    body: str
    features_present: list[str]
    version_bodies: list[str]  # v1..vn for versioning demos


def _fill(template: str, rng: random.Random) -> str:
    return template.format(
        cap=rng.choice(CAPS),
        deductible=rng.choice(["$10,000", "$25,000", "$5,000"]),
        years=rng.choice([1, 2, 3, 5]),
        days=rng.choice([15, 30, 60, 90]),
        date=rng.choice(["31 December 2026", "30 June 2027", "15 March 2028"]),
        jurisdiction=rng.choice(JURISDICTIONS),
        territory=rng.choice(TERRITORIES),
    )


def _build_document_body(
    doc_index: int,
    pages: int,
    feature_set: set[str],
    rng: random.Random,
    liability_cap: str | None = None,
) -> tuple[str, list[str]]:
    """Build multi-section body approximating `pages` pages (~2.5k chars/page)."""
    present: list[str] = []
    parts: list[str] = [
        f"SHARE PURCHASE AGREEMENT — Document {doc_index:04d}\n",
        f"This Agreement is entered into as of the Effective Date between Buyer and Seller.\n",
    ]
    target_chars = max(pages, 1) * 2500
    # Map features to section numbers
    feature_section = {
        "change_of_control": "5",
        "termination": "6",
        "assignment": "7",
        "indemnification": "8",
        "liability": "9",
        "non_compete": "10",
        "governing_law": "11",
        "unusual_obligations": "12",
    }
    for sec_id, title in SECTION_ORDER:
        parts.append(f"\n## Section {sec_id}. {title}\n")
        # Find feature for this section
        feat = next((f for f, s in feature_section.items() if s == sec_id), None)
        if feat and feat in feature_set:
            present.append(feat)
            for tmpl in CLAUSE_TEMPLATES[feat]:
                text = _fill(tmpl, rng)
                if feat == "liability" and liability_cap and "{cap}" in tmpl:
                    text = tmpl.format(
                        cap=liability_cap,
                        deductible="$10,000",
                        years=2,
                        days=30,
                        date="31 December 2026",
                        jurisdiction="Delaware",
                        territory="North America",
                    )
                parts.append(text + "\n")
                # Pad with boilerplate to reach page length
                parts.append(
                    "Without limiting the foregoing, the Parties acknowledge the commercial "
                    "intent of this provision and agree to interpret it in accordance with "
                    "applicable law and the overall transaction structure.\n"
                )
        else:
            parts.append(
                f"This Section {sec_id} sets forth standard terms regarding {title.lower()}. "
                "The Parties agree to negotiate in good faith any amendments required by "
                "applicable regulatory authorities.\n"
            )
            parts.append(
                "Any notice under this Section shall be delivered in writing to the addresses "
                "set forth in the preamble, and shall be deemed received upon confirmed delivery.\n"
            )
    body = "".join(parts)
    # Pad to approximate page count
    while len(body) < target_chars:
        body += (
            "\nAdditional schedule language and boilerplate disclosures are incorporated "
            "herein by reference as if fully set forth in this Agreement.\n"
        )
    return body, present


def generate_corpus(
    n_documents: int = 100,
    pages_per_doc: int = 100,
    n_matters: int = 10,
    seed: int = 42,
    versions_per_doc: int = 2,
) -> list[SyntheticFile]:
    """
    Generate a folder-preserving synthetic upload batch.

    Structure:
      Client {i}/Matter {j}/Transaction Documents/Agreements/SPA_{k}.pdf
      Client {i}/Matter {j}/Transaction Documents/Schedules/Schedule_{k}.pdf
    """
    rng = random.Random(seed)
    files: list[SyntheticFile] = []
    all_features = list(CLAUSE_TEMPLATES.keys())

    for i in range(n_documents):
        matter_idx = i % n_matters
        client_idx = matter_idx % max(1, n_matters // 2 or 1)
        client = f"Client {client_idx + 1}"
        matter = f"Project {chr(65 + (matter_idx % 26))}{matter_idx + 1}"
        # ~30% get "unusual" change-of-control / liability variants
        features = set(rng.sample(all_features, k=rng.randint(4, 7)))
        if i % 7 == 0:
            features.add("change_of_control")
            features.add("unusual_obligations")
        if i % 5 == 0:
            features.add("indemnification")
            features.add("liability")

        pages = pages_per_doc if pages_per_doc > 0 else rng.randint(20, 120)
        # Version chain: v1 base, later versions bump liability cap
        version_bodies: list[str] = []
        present: list[str] = []
        caps_seq = ["$50,000", "$75,000", "$100,000"]
        for v in range(max(1, versions_per_doc)):
            cap = caps_seq[min(v, len(caps_seq) - 1)]
            body, present = _build_document_body(
                i, pages, features, rng, liability_cap=cap if "liability" in features else None
            )
            version_bodies.append(body)

        folder = f"{client}/{matter}/Transaction Documents/Agreements"
        name = f"SPA_{i:04d}.pdf"
        files.append(
            SyntheticFile(
                relative_path=f"{folder}/{name}",
                name=name,
                document_type="spa",
                matter_name=matter,
                client_name=client,
                pages=pages,
                body=version_bodies[-1],
                features_present=sorted(set(present)),
                version_bodies=version_bodies,
            )
        )

        # Occasional schedule sibling to preserve multi-doc folders
        if i % 4 == 0:
            sched_folder = f"{client}/{matter}/Transaction Documents/Schedules"
            sched_name = f"Schedule_{i:04d}.pdf"
            sched_body = (
                f"SCHEDULE TO {name}\n\n"
                "## Section 1. Disclosure Items\n"
                "Seller discloses the following exceptions to the Representations.\n"
                "## Section 2. Material Contracts\n"
                "List of material contracts attached hereto.\n"
            )
            files.append(
                SyntheticFile(
                    relative_path=f"{sched_folder}/{sched_name}",
                    name=sched_name,
                    document_type="schedule",
                    matter_name=matter,
                    client_name=client,
                    pages=max(5, pages // 10),
                    body=sched_body * max(1, pages // 20),
                    features_present=[],
                    version_bodies=[sched_body * max(1, pages // 20)],
                )
            )
    return files
