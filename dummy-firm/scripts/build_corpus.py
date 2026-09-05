#!/usr/bin/env python3
"""Build the dummy-firm corpus from PCIJ PDFs, UNSC resolutions, and docs/ filings."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PCIJ_ZIP = ROOT / "data" / "CD-PCIJ_1-1-0_EN_PDF_ORIGINALSPLIT_FULL.zip"
UNSC_ZIP = ROOT / "data" / "CR-UNSC_2026-08-19_ALL_CSV_FULL.zip"
DOCS_DIR = REPO / "docs"
DATA = ROOT / "data"
FILES = ROOT / "files"

PCIJ_NAME = re.compile(
    r"PCIJ_([A-Z]+)_(\d+)_(.+?)_([A-Z0-9-]+)_([A-Z0-9-]+)_"
    r"(\d{4}-\d{2}-\d{2})_([A-Z-]+)_(\d+)_(.+)_EN\.pdf$"
)

DOC_TYPE_LABEL = {
    "JUD": "Judgment",
    "ORD": "Order",
    "ADV": "Advisory Opinion",
    "ANX": "Annex",
    "APP": "Application",
    "DEC": "Decision",
}

ISO_NAMES = {
    "AFG": "Afghanistan",
    "ALB": "Albania",
    "DZA": "Algeria",
    "ARG": "Argentina",
    "AUS": "Australia",
    "AUT": "Austria",
    "BEL": "Belgium",
    "BIH": "Bosnia and Herzegovina",
    "BRA": "Brazil",
    "BGR": "Bulgaria",
    "CAN": "Canada",
    "CHL": "Chile",
    "CHN": "China",
    "COL": "Colombia",
    "COD": "Democratic Republic of the Congo",
    "HRV": "Croatia",
    "CUB": "Cuba",
    "CYP": "Cyprus",
    "CSK": "Czechoslovakia",
    "CZE": "Czechia",
    "DNK": "Denmark",
    "EGY": "Egypt",
    "EST": "Estonia",
    "ETH": "Ethiopia",
    "FIN": "Finland",
    "FRA": "France",
    "DEU": "Germany",
    "GRC": "Greece",
    "HTI": "Haiti",
    "HUN": "Hungary",
    "IND": "India",
    "IDN": "Indonesia",
    "IRN": "Iran",
    "IRQ": "Iraq",
    "IRL": "Ireland",
    "ISR": "Israel",
    "ITA": "Italy",
    "JPN": "Japan",
    "JOR": "Jordan",
    "KEN": "Kenya",
    "KWT": "Kuwait",
    "LBN": "Lebanon",
    "LBY": "Libya",
    "LTU": "Lithuania",
    "LUX": "Luxembourg",
    "MYS": "Malaysia",
    "MLI": "Mali",
    "MLT": "Malta",
    "MEX": "Mexico",
    "MNE": "Montenegro",
    "MAR": "Morocco",
    "NLD": "Netherlands",
    "NZL": "New Zealand",
    "NIC": "Nicaragua",
    "NGA": "Nigeria",
    "PRK": "Democratic People's Republic of Korea",
    "NOR": "Norway",
    "PAK": "Pakistan",
    "PAN": "Panama",
    "PRY": "Paraguay",
    "PER": "Peru",
    "PHL": "Philippines",
    "POL": "Poland",
    "PRT": "Portugal",
    "QAT": "Qatar",
    "KOR": "Republic of Korea",
    "ROU": "Romania",
    "RUS": "Russian Federation",
    "SAU": "Saudi Arabia",
    "SEN": "Senegal",
    "SRB": "Serbia",
    "SLE": "Sierra Leone",
    "SGP": "Singapore",
    "SVK": "Slovakia",
    "SVN": "Slovenia",
    "SOM": "Somalia",
    "ZAF": "South Africa",
    "SSD": "South Sudan",
    "ESP": "Spain",
    "LKA": "Sri Lanka",
    "SDN": "Sudan",
    "SWE": "Sweden",
    "CHE": "Switzerland",
    "SYR": "Syrian Arab Republic",
    "TZA": "United Republic of Tanzania",
    "THA": "Thailand",
    "TUN": "Tunisia",
    "TUR": "Türkiye",
    "UGA": "Uganda",
    "UKR": "Ukraine",
    "ARE": "United Arab Emirates",
    "GBR": "United Kingdom",
    "USA": "United States of America",
    "URY": "Uruguay",
    "VEN": "Venezuela",
    "VNM": "Viet Nam",
    "YEM": "Yemen",
    "YUG": "Yugoslavia",
    "ZWE": "Zimbabwe",
    "LNC": "League of Nations Council",
    "PCI": "Permanent Court of International Justice",
}

MEMBERS = [
    {
        "member_id": "MEM-00001",
        "name": "Helena Voss",
        "role": "Partner",
        "practice_areas": ["Disputes", "Arbitration"],
        "specializations": ["PCIJ jurisprudence", "State responsibility"],
        "office": "The Hague",
        "joined_year": 2009,
        "email": "helena.voss@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00002",
        "name": "Rafael Okonkwo",
        "role": "Partner",
        "practice_areas": ["Regulatory", "Disputes"],
        "specializations": ["UN Charter", "Peacekeeping mandates"],
        "office": "New York",
        "joined_year": 2011,
        "email": "rafael.okonkwo@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00003",
        "name": "Ingrid Bergström",
        "role": "Counsel",
        "practice_areas": ["Disputes", "Arbitration"],
        "specializations": ["Advisory opinions", "Treaty interpretation"],
        "office": "The Hague",
        "joined_year": 2014,
        "email": "ingrid.bergstrom@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00004",
        "name": "Sami Haddad",
        "role": "Counsel",
        "practice_areas": ["Regulatory", "Disputes"],
        "specializations": ["Sanctions", "Chapter VII"],
        "office": "Geneva",
        "joined_year": 2015,
        "email": "sami.haddad@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00005",
        "name": "Priya Menon",
        "role": "Senior Associate",
        "practice_areas": ["Disputes"],
        "specializations": ["Historical awards", "Boundary disputes"],
        "office": "The Hague",
        "joined_year": 2018,
        "email": "priya.menon@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00006",
        "name": "Jonas Kruk",
        "role": "Senior Associate",
        "practice_areas": ["Regulatory"],
        "specializations": ["Mandate renewals", "Force composition"],
        "office": "New York",
        "joined_year": 2017,
        "email": "jonas.kruk@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00007",
        "name": "Amina El-Sayed",
        "role": "Associate",
        "practice_areas": ["Disputes", "Regulatory"],
        "specializations": ["Documentary annexes", "Voting records"],
        "office": "Geneva",
        "joined_year": 2020,
        "email": "amina.elsayed@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00008",
        "name": "Tomás Ribeiro",
        "role": "Associate",
        "practice_areas": ["Arbitration"],
        "specializations": ["Compensation", "Factory at Chorzów line"],
        "office": "The Hague",
        "joined_year": 2021,
        "email": "tomas.ribeiro@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00009",
        "name": "Mei Lin",
        "role": "Junior",
        "practice_areas": ["Disputes"],
        "specializations": ["Case chronology"],
        "office": "The Hague",
        "joined_year": 2023,
        "email": "mei.lin@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00010",
        "name": "Owen Blake",
        "role": "Junior",
        "practice_areas": ["Regulatory"],
        "specializations": ["Resolution citators"],
        "office": "New York",
        "joined_year": 2024,
        "email": "owen.blake@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00011",
        "name": "Clara Dufour",
        "role": "Knowledge Manager",
        "practice_areas": ["Disputes", "Regulatory"],
        "specializations": ["Corpus cataloguing"],
        "office": "The Hague",
        "joined_year": 2016,
        "email": "clara.dufour@harbourchambers.int",
        "is_lawyer": False,
    },
    {
        "member_id": "MEM-00012",
        "name": "Noah Patel",
        "role": "Paralegal",
        "practice_areas": ["Disputes"],
        "specializations": ["PDF splitting", "Pagination"],
        "office": "The Hague",
        "joined_year": 2022,
        "email": "noah.patel@harbourchambers.int",
        "is_lawyer": False,
    },
    {
        "member_id": "MEM-00013",
        "name": "Ananya Deshmukh",
        "role": "Partner",
        "practice_areas": ["Regulatory", "Disputes"],
        "specializations": ["Electricity regulation", "Change in law"],
        "office": "Delhi",
        "joined_year": 2012,
        "email": "ananya.deshmukh@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00014",
        "name": "Vikram Sethi",
        "role": "Counsel",
        "practice_areas": ["Regulatory", "Disputes"],
        "specializations": ["APTEL appeals", "Transmission connectivity"],
        "office": "Delhi",
        "joined_year": 2016,
        "email": "vikram.sethi@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00015",
        "name": "Rhea Kapoor",
        "role": "Senior Associate",
        "practice_areas": ["Regulatory"],
        "specializations": ["PPA disputes", "GST under reverse charge"],
        "office": "Delhi",
        "joined_year": 2019,
        "email": "rhea.kapoor@harbourchambers.int",
        "is_lawyer": True,
    },
    {
        "member_id": "MEM-00016",
        "name": "Arjun Nair",
        "role": "Associate",
        "practice_areas": ["Disputes", "Regulatory"],
        "specializations": ["Affidavits", "Interim applications"],
        "office": "Delhi",
        "joined_year": 2022,
        "email": "arjun.nair@harbourchambers.int",
        "is_lawyer": True,
    },
]

INDIA_MATTERS = [
    {
        "slug": "SCI-CA-10046-2025",
        "title": "MSEDCL v MERC — Civil Appeal 10046 of 2025",
        "client": "Maharashtra State Electricity Distribution Company Limited",
        "opposing": "Maharashtra Electricity Regulatory Commission",
        "court": "Supreme Court of India",
        "practice_area": "Regulatory",
        "matter_type": "Civil Appeal",
        "opened_date": "2025-08-01",
        "closed_date": None,
        "status": "Open",
        "issues": [
            "Additional affidavit in Civil Appeal 10046 of 2025",
            "MSEDCL appellate challenge from MERC",
        ],
        "facts": [
            "MSEDCL is the appellant before the Supreme Court in C.A. No. 10046 of 2025.",
            "The record includes an additional affidavit with annexures A1–A4 dated 10 August 2026.",
        ],
        "docs": [
            {
                "filename": "Affidavit - CA 10046 of 2025.pdf",
                "document_type": "Affidavit",
                "date": "2026-08-10",
                "title": "Additional affidavit on behalf of MSEDCL in C.A. 10046 of 2025",
            }
        ],
    },
    {
        "slug": "APTEL-APL-163-2018",
        "title": "GMR Warora Energy v CERC — Appeal 163 of 2018",
        "client": "Maharashtra State Electricity Distribution Company Limited",
        "opposing": "GMR Warora Energy Limited",
        "court": "Appellate Tribunal for Electricity",
        "practice_area": "Regulatory",
        "matter_type": "Electricity Appeal",
        "opened_date": "2018-01-01",
        "closed_date": None,
        "status": "Open",
        "issues": [
            "Change in law compensation under PPAs",
            "CERC order dated 16 March 2018 in Petition 1/MP/2017",
        ],
        "facts": [
            "GMR Warora Energy Limited appealed CERC's change-in-law findings.",
            "MSEDCL filed a brief note as Respondent No. 2 before APTEL.",
        ],
        "docs": [
            {
                "filename": "BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf",
                "document_type": "Written Submission",
                "date": "2018-06-01",
                "title": "Brief note of submissions on behalf of MSEDCL in Appeal 163 of 2018",
            },
            {
                "filename": "MSEDCL Note in APL. 163 of 2018.pdf",
                "document_type": "Hearing Notes",
                "date": "2018-06-01",
                "title": "MSEDCL note in Appeal 163 of 2018",
            },
        ],
    },
    {
        "slug": "CERC-310-MP-2026",
        "title": "AMPIN Energy Utility Nine v CTUIL — Petition 310/MP/2026",
        "client": "Central Transmission Utility of India Limited",
        "opposing": "AMPIN Energy Utility Nine Pvt. Ltd.",
        "court": "Central Electricity Regulatory Commission",
        "practice_area": "Regulatory",
        "matter_type": "CERC Petition",
        "opened_date": "2026-01-01",
        "closed_date": None,
        "status": "Open",
        "issues": [
            "Reply of CTUIL in Petition 310/MP/2026",
            "CMETS connectivity minutes",
        ],
        "facts": [
            "AMPIN Energy Utility Nine Pvt. Ltd. petitioned CERC against CTUIL.",
            "CTUIL filed a reply with extracts of the 47th CMETS minutes dated 20 July 2026.",
        ],
        "docs": [
            {
                "filename": "Final Reply (310-MP-2026).pdf",
                "document_type": "Written Submission",
                "date": "2026-08-25",
                "title": "Reply on behalf of CTUIL in Petition 310/MP/2026",
            }
        ],
    },
    {
        "slug": "APTEL-APL-118-2025",
        "title": "WBSEDCL v WBERC — Appeal 118 of 2025 (DVC impleadment)",
        "client": "Damodar Valley Corporation",
        "opposing": "West Bengal State Electricity Distribution Company Limited",
        "court": "Appellate Tribunal for Electricity",
        "practice_area": "Regulatory",
        "matter_type": "Impleadment Application",
        "opened_date": "2025-01-01",
        "closed_date": None,
        "status": "Open",
        "issues": [
            "Impleadment of Damodar Valley Corporation",
            "I.A. No. 1548 of 2026 in Appeal 118 of 2025",
        ],
        "facts": [
            "WBSEDCL appealed against WBERC.",
            "DVC sought impleadment and rejoined WBSEDCL's reply dated 6 August 2026.",
        ],
        "docs": [
            {
                "filename": "Rejoinder to Reply to Impleadment Application.pdf",
                "document_type": "Rejoinder",
                "date": "2026-08-21",
                "title": "DVC rejoinder to WBSEDCL reply on impleadment in Appeal 118 of 2025",
            }
        ],
    },
    {
        "slug": "APTEL-DFR-274-2026",
        "title": "HPSEBL v HPPCL — DFR 274 of 2026 (stay)",
        "client": "Himachal Pradesh State Electricity Board Limited",
        "opposing": "Himachal Pradesh Power Corporation Limited",
        "court": "Appellate Tribunal for Electricity",
        "practice_area": "Regulatory",
        "matter_type": "Interim Application",
        "opened_date": "2026-01-01",
        "closed_date": None,
        "status": "Open",
        "issues": [
            "Stay application I.A. No. 1097 of 2026",
            "Rejoinder to HPPCL reply",
        ],
        "facts": [
            "HPSEBL filed DFR No. 274 of 2026 against HPPCL.",
            "The appellant rejoined the reply to the interim stay application.",
        ],
        "docs": [
            {
                "filename": "Rejoinder to reply of IA.pdf",
                "document_type": "Rejoinder",
                "date": "2026-08-11",
                "title": "HPSEBL rejoinder to HPPCL reply in I.A. 1097 of 2026",
            }
        ],
    },
    {
        "slug": "PSERC-PET-22-2026",
        "title": "Vector Green Sunshine v PSPCL — Petition 22 of 2026",
        "client": "Punjab State Power Corporation Limited",
        "opposing": "Vector Green Sunshine Pvt. Ltd.",
        "court": "Punjab State Electricity Regulatory Commission",
        "practice_area": "Regulatory",
        "matter_type": "State Commission Petition",
        "opened_date": "2026-01-01",
        "closed_date": None,
        "status": "Open",
        "issues": [
            "GST reverse charge on renting of immovable property",
            "Change in law / compensation under the PPA",
        ],
        "facts": [
            "Vector Green Sunshine Pvt. Ltd. petitioned PSERC for GST-RCM compensation.",
            "PSPCL filed written submissions dated 31 July 2026.",
        ],
        "docs": [
            {
                "filename": "WRITTEN SUBMISSION IN PETITION NO. 22 OF 2026 (VECTOR GREEN) 01.08.2026.pdf",
                "document_type": "Written Submission",
                "date": "2026-07-31",
                "title": "PSPCL written submissions in Petition 22 of 2026 (Vector Green)",
            }
        ],
    },
]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def title_case_slug(slug: str) -> str:
    slug = slug.replace("-", " ")
    return re.sub(r"(?<!^)(?=[A-Z])", " ", slug).replace("  ", " ").strip()


def party_name(code: str) -> str | None:
    if not code or code == "NA":
        return None
    return ISO_NAMES.get(code, code.replace("-", " "))


def split_parties(raw: str) -> list[str]:
    if not raw or raw == "NA":
        return []
    return [p for p in raw.split("-") if p and p != "NA"]


def extract_pdf_text(pdf_path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def team_for(index: int, office: str) -> list[dict[str, str]]:
    lawyers = [m for m in MEMBERS if m["is_lawyer"] and m["office"] == office]
    if len(lawyers) < 3:
        lawyers = [m for m in MEMBERS if m["is_lawyer"]]
    support = [m for m in MEMBERS if not m["is_lawyer"]]
    lead = lawyers[index % len(lawyers)]
    associate = lawyers[(index + 1) % len(lawyers)]
    junior = lawyers[(index + 2) % len(lawyers)]
    clerk = support[index % len(support)]
    return [
        {"member_id": lead["member_id"], "role_on_matter": "Lead"},
        {"member_id": associate["member_id"], "role_on_matter": "Associate"},
        {"member_id": junior["member_id"], "role_on_matter": "Junior"},
        {"member_id": clerk["member_id"], "role_on_matter": clerk["role"]},
    ]


def member_name(member_id: str) -> str:
    return next(m["name"] for m in MEMBERS if m["member_id"] == member_id)


def ensure_client(
    clients: dict[str, dict],
    name: str,
    industry: str,
    hq: str,
    preferred: list[str],
) -> str:
    for client in clients.values():
        if client["name"] == name:
            return client["client_id"]
    client_id = f"CLI-{len(clients) + 1:05d}"
    alias = name.split("(")[0].strip()
    clients[client_id] = {
        "client_id": client_id,
        "name": name,
        "industry": industry,
        "size": "Sovereign" if industry == "State" else "Institution",
        "headquarters": hq,
        "locations": [hq],
        "subsidiaries": [],
        "preferred_lawyer_ids": preferred,
        "aliases": [name] if name == alias else [name, alias],
    }
    return client_id


def build_pcij(clients: dict[str, dict]) -> tuple[list[dict], list[dict], dict[str, dict]]:
    if not PCIJ_ZIP.exists():
        raise FileNotFoundError(PCIJ_ZIP)

    cases: dict[str, dict] = {}
    with zipfile.ZipFile(PCIJ_ZIP) as archive:
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        for name in pdfs:
            filename = Path(name).name
            match = PCIJ_NAME.match(filename)
            if not match:
                raise ValueError(f"Unparsed PCIJ filename: {filename}")
            series, number, case, applicants, respondents, doc_date, dtype, seq, rest = match.groups()
            case_key = f"{series}_{number}_{case}"
            slug = f"PCIJ-{series}-{number}-{case}"
            dest_dir = FILES / "pcij" / slug
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            if not dest.exists():
                dest.write_bytes(archive.read(name))
            record = cases.setdefault(
                case_key,
                {
                    "series": series,
                    "number": number,
                    "case": case,
                    "slug": slug,
                    "applicants": split_parties(applicants),
                    "respondents": split_parties(respondents),
                    "docs": [],
                },
            )
            record["docs"].append(
                {
                    "filename": filename,
                    "path": dest,
                    "date": doc_date,
                    "dtype": dtype,
                    "seq": seq,
                    "rest": rest,
                    "applicants": split_parties(applicants),
                    "respondents": split_parties(respondents),
                }
            )

    matters: list[dict] = []
    documents: list[dict] = []
    dnas: dict[str, dict] = {}
    matter_index = 0
    doc_index = 0

    for case_key in sorted(cases, key=lambda k: (cases[k]["series"], int(cases[k]["number"]), k)):
        case = cases[case_key]
        case["docs"].sort(key=lambda d: (d["date"], d["dtype"], d["seq"], d["filename"]))
        title_core = title_case_slug(case["case"])
        applicant_names = [party_name(c) or c for c in case["applicants"]]
        respondent_names = [party_name(c) or c for c in case["respondents"]]
        client_name = applicant_names[0] if applicant_names else "League of Nations Council"
        opposing = ", ".join(respondent_names) if respondent_names else "Advisory proceeding"
        preferred = ["MEM-00001", "MEM-00003"]
        client_id = ensure_client(clients, client_name, "State", "The Hague", preferred)
        opened = case["docs"][0]["date"]
        closed = case["docs"][-1]["date"]
        year = opened[:4]
        matter_index += 1
        matter_id = f"MTR-{year}-{matter_index:05d}"
        matter_code = f"PIL/HAG/{matter_index:04d}/{year}"
        team = team_for(matter_index, "The Hague")
        issues = [
            "Jurisdiction of the Permanent Court of International Justice",
            f"{title_core} merits",
        ]
        facts = [
            f"PCIJ Series {case['series']} No. {int(case['number'])}: {title_core}.",
            f"Applicant(s): {', '.join(applicant_names) or 'not specified'}.",
            f"Respondent(s): {', '.join(respondent_names) or 'advisory / no respondent'}.",
            f"The file contains {len(case['docs'])} original English PDFs.",
        ]
        matter = {
            "matter_id": matter_id,
            "matter_code": matter_code,
            "title": f"{title_core} — PCIJ Series {case['series']} No. {int(case['number'])}",
            "client_id": client_id,
            "client_name": client_name,
            "opposing_party": opposing,
            "practice_area": "Disputes",
            "matter_type": "Permanent Court of International Justice",
            "theme_key": f"pcij_{case['slug'].lower()}",
            "jurisdiction": "International",
            "court": "Permanent Court of International Justice",
            "opened_date": opened,
            "closed_date": closed,
            "status": "Closed",
            "office": "The Hague",
            "matter_members": team,
            "claim_amount": None,
            "outcome": "Judgment or order on the PCIJ docket",
            "legal_issues": issues,
            "facts": facts,
        }
        matters.append(matter)
        dnas[matter_id] = {
            "matter_id": matter_id,
            "theme_key": matter["theme_key"],
            "theme_label": title_core,
            "facts": facts,
            "legal_issues": issues,
            "arguments": [f"The Court should determine the {title_core} dispute on the documents filed."],
            "counterarguments": ["The Court lacked jurisdiction or the claim was inadmissible."],
            "amounts": {},
            "forums": ["Permanent Court of International Justice"],
            "outcome": matter["outcome"],
            "claim_amount": None,
            "court": matter["court"],
        }
        lead = team[0]["member_id"]
        for doc in case["docs"]:
            doc_index += 1
            document_id = f"DOC-{doc_index:05d}"
            label = DOC_TYPE_LABEL.get(doc["dtype"], doc["dtype"])
            text = extract_pdf_text(doc["path"])
            if not text:
                text = (
                    f"{label} in {title_core} dated {doc['date']}. "
                    f"Source file: {doc['filename']}."
                )
            documents.append(
                {
                    "document_id": document_id,
                    "matter_id": matter_id,
                    "matter_code": matter_code,
                    "client_id": client_id,
                    "title": f"{label} — {title_core} ({doc['date']})",
                    "document_type": label,
                    "author_id": lead,
                    "author_name": member_name(lead),
                    "date": doc["date"],
                    "status": "Final",
                    "version": None,
                    "parent_document_id": None,
                    "version_group": None,
                    "contains_amount": False,
                    "contains_court": True,
                    "contains_weather_fact": False,
                    "source_path": str(doc["path"].relative_to(ROOT)),
                    "text": text,
                }
            )
            print(f"pcij {document_id} {doc['filename']}", flush=True)
    return matters, documents, dnas


def build_unsc(
    clients: dict[str, dict],
    start_matter: int,
    start_doc: int,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    if not UNSC_ZIP.exists():
        raise FileNotFoundError(UNSC_ZIP)

    by_year: dict[str, list[dict]] = defaultdict(list)
    with zipfile.ZipFile(UNSC_ZIP) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            wrapper = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for row in csv.DictReader(wrapper):
                year = (row.get("year") or "").strip()
                if not year:
                    continue
                by_year[year].append(row)

    un_id = ensure_client(
        clients,
        "United Nations",
        "Intergovernmental organisation",
        "New York",
        ["MEM-00002", "MEM-00004"],
    )

    matters: list[dict] = []
    documents: list[dict] = []
    dnas: dict[str, dict] = {}
    matter_index = start_matter
    doc_index = start_doc

    for year in sorted(by_year, key=int):
        rows = sorted(
            by_year[year],
            key=lambda r: ((r.get("date") or ""), int(r.get("res_no") or 0) if str(r.get("res_no") or "").isdigit() else 0),
        )
        matter_index += 1
        matter_id = f"MTR-{year}-{matter_index:05d}"
        matter_code = f"REG/NYC/{matter_index:04d}/{year}"
        team = team_for(matter_index, "New York")
        topics = []
        for row in rows:
            topic = (row.get("topic") or "").strip()
            if topic and topic.upper() != "NA" and topic not in topics:
                topics.append(topic)
        issues = topics[:8] or [f"UN Security Council practice in {year}"]
        facts = [
            f"{len(rows)} Security Council resolutions adopted in {year}.",
            f"Leading topics include: {'; '.join(topics[:5]) or 'general peace and security'}.",
        ]
        last_date = rows[-1].get("date") or f"{year}-12-31"
        status = "Open" if int(year) >= 2025 else "Closed"
        matter = {
            "matter_id": matter_id,
            "matter_code": matter_code,
            "title": f"UN Security Council resolutions — {year}",
            "client_id": un_id,
            "client_name": "United Nations",
            "opposing_party": "Member States (situation-specific)",
            "practice_area": "Regulatory",
            "matter_type": "Security Council Resolution",
            "theme_key": f"unsc_{year}",
            "jurisdiction": "International",
            "court": "United Nations Security Council",
            "opened_date": rows[0].get("date") or f"{year}-01-01",
            "closed_date": None if status == "Open" else last_date,
            "status": status,
            "office": "New York",
            "matter_members": team,
            "claim_amount": None,
            "outcome": "Resolutions adopted",
            "legal_issues": issues,
            "facts": facts,
        }
        matters.append(matter)
        dnas[matter_id] = {
            "matter_id": matter_id,
            "theme_key": matter["theme_key"],
            "theme_label": f"UNSC {year}",
            "facts": facts,
            "legal_issues": issues,
            "arguments": [f"Council action in {year} should be read from the adopted resolutions."],
            "counterarguments": ["A resolution may not bind in the manner claimed without Chapter VII language."],
            "amounts": {},
            "forums": ["United Nations Security Council"],
            "outcome": matter["outcome"],
            "claim_amount": None,
            "court": matter["court"],
        }
        year_dir = FILES / "unsc" / year
        year_dir.mkdir(parents=True, exist_ok=True)
        lead = team[0]["member_id"]
        for row in rows:
            doc_index += 1
            document_id = f"DOC-{doc_index:05d}"
            symbol = (row.get("symbol") or row.get("doc_id") or document_id).strip()
            title = (row.get("title") or symbol).strip()
            text = (row.get("text") or "").strip()
            summary = (row.get("summary") or "").strip()
            if summary and summary.upper() != "NA":
                text = f"{summary}\n\n{text}".strip()
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol) + ".txt"
            dest = year_dir / safe
            dest.write_text(text + "\n", encoding="utf-8")
            date = (row.get("date") or f"{year}-01-01").strip()
            documents.append(
                {
                    "document_id": document_id,
                    "matter_id": matter_id,
                    "matter_code": matter_code,
                    "client_id": un_id,
                    "title": title,
                    "document_type": "Security Council Resolution",
                    "author_id": lead,
                    "author_name": member_name(lead),
                    "date": date,
                    "status": "Final",
                    "version": None,
                    "parent_document_id": None,
                    "version_group": None,
                    "contains_amount": False,
                    "contains_court": True,
                    "contains_weather_fact": False,
                    "source_path": str(dest.relative_to(ROOT)),
                    "symbol": symbol,
                    "text": text,
                }
            )
        print(f"unsc year {year} docs={len(rows)} matter={matter_id}", flush=True)
    return matters, documents, dnas


def build_india(
    clients: dict[str, dict],
    start_matter: int,
    start_doc: int,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    if not DOCS_DIR.is_dir():
        raise FileNotFoundError(DOCS_DIR)

    matters: list[dict] = []
    documents: list[dict] = []
    dnas: dict[str, dict] = {}
    matter_index = start_matter
    doc_index = start_doc

    for spec in INDIA_MATTERS:
        matter_index += 1
        year = spec["opened_date"][:4]
        matter_id = f"MTR-{year}-{matter_index:05d}"
        matter_code = f"REG/DEL/{matter_index:04d}/{year}"
        team = team_for(matter_index, "Delhi")
        preferred = ["MEM-00013", "MEM-00014"]
        client_id = ensure_client(clients, spec["client"], "Energy utility", "India", preferred)
        dest_dir = FILES / "india-energy" / spec["slug"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        matter = {
            "matter_id": matter_id,
            "matter_code": matter_code,
            "title": spec["title"],
            "client_id": client_id,
            "client_name": spec["client"],
            "opposing_party": spec["opposing"],
            "practice_area": spec["practice_area"],
            "matter_type": spec["matter_type"],
            "theme_key": f"india_{spec['slug'].lower()}",
            "jurisdiction": "India",
            "court": spec["court"],
            "opened_date": spec["opened_date"],
            "closed_date": spec["closed_date"],
            "status": spec["status"],
            "office": "Delhi",
            "matter_members": team,
            "claim_amount": None,
            "outcome": None,
            "legal_issues": spec["issues"],
            "facts": spec["facts"],
        }
        matters.append(matter)
        dnas[matter_id] = {
            "matter_id": matter_id,
            "theme_key": matter["theme_key"],
            "theme_label": spec["title"],
            "facts": spec["facts"],
            "legal_issues": spec["issues"],
            "arguments": spec["facts"][:1],
            "counterarguments": ["The opposing party's claims are not made out on these papers."],
            "amounts": {},
            "forums": [spec["court"]],
            "outcome": None,
            "claim_amount": None,
            "court": spec["court"],
        }
        lead = team[0]["member_id"]
        for doc_spec in spec["docs"]:
            src = DOCS_DIR / doc_spec["filename"]
            if not src.exists():
                raise FileNotFoundError(src)
            dest = dest_dir / doc_spec["filename"]
            if dest.resolve() != src.resolve():
                shutil.copy2(src, dest)
            text = extract_pdf_text(dest)
            if len(text) < 40:
                text = (
                    f"{doc_spec['title']}. Forum: {spec['court']}. "
                    f"Parties: {spec['client']} v {spec['opposing']}. "
                    f"Source file: {doc_spec['filename']}."
                )
            doc_index += 1
            documents.append(
                {
                    "document_id": f"DOC-{doc_index:05d}",
                    "matter_id": matter_id,
                    "matter_code": matter_code,
                    "client_id": client_id,
                    "title": doc_spec["title"],
                    "document_type": doc_spec["document_type"],
                    "author_id": lead,
                    "author_name": member_name(lead),
                    "date": doc_spec["date"],
                    "status": "Final",
                    "version": None,
                    "parent_document_id": None,
                    "version_group": None,
                    "contains_amount": False,
                    "contains_court": True,
                    "contains_weather_fact": False,
                    "source_path": str(dest.relative_to(ROOT)),
                    "text": text,
                }
            )
            print(f"india {documents[-1]['document_id']} {doc_spec['filename']}", flush=True)
    return matters, documents, dnas


def build_relationships(matters: list[dict]) -> list[dict]:
    rels: list[dict] = []
    by_client: dict[str, list[str]] = defaultdict(list)
    by_theme_family: dict[str, list[str]] = defaultdict(list)
    for matter in matters:
        by_client[matter["client_id"]].append(matter["matter_id"])
        family = "pcij" if matter["theme_key"].startswith("pcij_") else "unsc"
        by_theme_family[family].append(matter["matter_id"])

    seen: set[tuple[str, str, str]] = set()

    def emit(source: str, rel: str, target: str) -> None:
        if source == target:
            return
        key = (source, rel, target)
        if key in seen:
            return
        seen.add(key)
        rels.append({"source": source, "type": rel, "target": target})

    for ids in by_client.values():
        for i, source in enumerate(ids):
            for target in ids[i + 1 : i + 6]:
                emit(source, "same_client", target)

    pcij = [m for m in matters if m["theme_key"].startswith("pcij_")]
    for i, source in enumerate(pcij):
        stem = re.sub(r"(indemnities|interpretation|readaptation).*$", "", source["title"], flags=re.I)
        for later in pcij[i + 1 :]:
            if later["title"].startswith(stem[:24]) and later["matter_id"] != source["matter_id"]:
                emit(source["matter_id"], "precedent_for", later["matter_id"])
                emit(source["matter_id"], "similar_facts", later["matter_id"])

    unsc = [m for m in matters if m["theme_key"].startswith("unsc_")]
    for i, source in enumerate(unsc[:-1]):
        emit(source["matter_id"], "follow_up_to", unsc[i + 1]["matter_id"])
        emit(source["matter_id"], "same_practice_area", unsc[i + 1]["matter_id"])

    india = [m for m in matters if m["theme_key"].startswith("india_")]
    for i, source in enumerate(india):
        for target in india[i + 1 :]:
            emit(source["matter_id"], "same_practice_area", target["matter_id"])
            emit(source["matter_id"], "similar_facts", target["matter_id"])
    return rels


def build_permissions(matters: list[dict]) -> list[dict]:
    rows = []
    for matter in matters:
        team = [item["member_id"] for item in matter["matter_members"]]
        rows.append(
            {
                "matter_id": matter["matter_id"],
                "classification": f"{matter['practice_area']} team",
                "restricted": False,
                "allowed_members": team,
                "practice_area": matter["practice_area"],
            }
        )
    return rows


def build_arguments(matters: list[dict], documents: list[dict]) -> list[dict]:
    by_matter: dict[str, list[str]] = defaultdict(list)
    for doc in documents:
        by_matter[doc["matter_id"]].append(doc["document_id"])
    rows = []
    for index, matter in enumerate(matters, start=1):
        support = by_matter[matter["matter_id"]][:5]
        rows.append(
            {
                "argument_id": f"ARG-{index:05d}",
                "matter_id": matter["matter_id"],
                "issue": (matter["legal_issues"] or ["International law"])[0],
                "position": "Client",
                "argument": matter["facts"][0] if matter["facts"] else matter["title"],
                "outcome": matter.get("outcome"),
                "supporting_documents": support,
            }
        )
    return rows


def build_entities(matters: list[dict], clients: list[dict]) -> list[dict]:
    rows = []
    for member in MEMBERS:
        rows.append(
            {
                "entity_id": member["member_id"],
                "type": "PERSON",
                "name": member["name"],
                "role": member["role"],
            }
        )
    for client in clients:
        rows.append(
            {
                "entity_id": client["client_id"],
                "type": "CLIENT",
                "name": client["name"],
                "role": client.get("industry"),
            }
        )
    rows.append(
        {
            "entity_id": "CRT-PCIJ",
            "type": "COURT",
            "name": "Permanent Court of International Justice",
            "role": "Court",
        }
    )
    rows.append(
        {
            "entity_id": "CRT-UNSC",
            "type": "COURT",
            "name": "United Nations Security Council",
            "role": "Organ",
        }
    )
    seen_issues: set[str] = set()
    for matter in matters:
        for issue in matter.get("legal_issues") or []:
            if issue in seen_issues:
                continue
            seen_issues.add(issue)
            rows.append(
                {
                    "entity_id": f"ISS-{len(seen_issues):05d}",
                    "type": "LEGAL_ISSUE",
                    "name": issue,
                    "role": matter["practice_area"],
                }
            )
    return rows


def build_evaluation(matters: list[dict], documents: list[dict]) -> list[dict]:
    by_matter: dict[str, list[str]] = defaultdict(list)
    for doc in documents:
        by_matter[doc["matter_id"]].append(doc["document_id"])
    questions = []
    pcij = [m for m in matters if m["theme_key"].startswith("pcij_")]
    unsc = [m for m in matters if m["theme_key"].startswith("unsc_")]
    india = [m for m in matters if m["theme_key"].startswith("india_")]
    for matter in pcij[:20] + unsc[:10] + india:
        qid = f"Q-{len(questions) + 1:04d}"
        questions.append(
            {
                "question_id": qid,
                "type": "exact",
                "level": 1,
                "question": f"What is the matter code for {matter['title']}?",
                "expected_answer": matter["matter_code"],
                "expected_matters": [matter["matter_id"]],
                "expected_documents": by_matter[matter["matter_id"]][:8],
            }
        )
    return questions


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    clients: dict[str, dict] = {}

    pcij_matters, pcij_docs, pcij_dna = build_pcij(clients)
    unsc_matters, unsc_docs, unsc_dna = build_unsc(
        clients,
        start_matter=len(pcij_matters),
        start_doc=len(pcij_docs),
    )
    india_matters, india_docs, india_dna = build_india(
        clients,
        start_matter=len(pcij_matters) + len(unsc_matters),
        start_doc=len(pcij_docs) + len(unsc_docs),
    )

    matters = pcij_matters + unsc_matters + india_matters
    documents = pcij_docs + unsc_docs + india_docs
    dnas = {**pcij_dna, **unsc_dna, **india_dna}
    client_list = list(clients.values())
    relationships = build_relationships(matters)
    permissions = build_permissions(matters)
    arguments = build_arguments(matters, documents)
    entities = build_entities(matters, client_list)
    evaluation = build_evaluation(matters, documents)

    write_json(DATA / "members.json", MEMBERS)
    write_json(DATA / "clients.json", client_list)
    write_json(DATA / "matters.json", matters)
    write_json(DATA / "matter_dna.json", list(dnas.values()))
    write_json(DATA / "permissions.json", permissions)
    write_jsonl(DATA / "documents.jsonl", documents)
    write_jsonl(DATA / "relationships.jsonl", relationships)
    write_jsonl(DATA / "arguments.jsonl", arguments)
    write_jsonl(DATA / "entities.jsonl", entities)
    write_jsonl(DATA / "evaluation.jsonl", evaluation)
    summary = {
        "firm": "Harbour International Chambers",
        "profile": "public_records",
        "members": len(MEMBERS),
        "clients": len(client_list),
        "matters": len(matters),
        "pcij_matters": len(pcij_matters),
        "unsc_matters": len(unsc_matters),
        "india_matters": len(india_matters),
        "documents": len(documents),
        "pcij_documents": len(pcij_docs),
        "unsc_documents": len(unsc_docs),
        "india_documents": len(india_docs),
        "relationships": len(relationships),
        "arguments": len(arguments),
        "entities": len(entities),
        "evaluation_questions": len(evaluation),
        "restricted_matters": 0,
    }
    write_json(DATA / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
