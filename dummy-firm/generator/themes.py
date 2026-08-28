from __future__ import annotations

from typing import Any


# Each theme is a reusable "world" that similar matters can share with wording drift.
THEMES: dict[str, dict[str, Any]] = {
    "flood_force_majeure": {
        "label": "Construction delay / flooding / force majeure",
        "practice_areas": ["Arbitration", "Disputes"],
        "matter_types": ["Construction Arbitration", "Construction Dispute"],
        "facts": [
            "EPC contractor delayed project completion",
            "Delay caused by flooding / extreme rainfall",
            "Employer imposed liquidated damages",
            "Contractor invoked force majeure",
            "Independent engineer certified weather disruption",
        ],
        "legal_issues": ["Force majeure", "Liquidated damages", "Contractual delay", "Causation"],
        "arguments": [
            "Flooding constituted force majeure",
            "Delay was outside contractor control",
            "Liquidated damages were disproportionate",
        ],
        "counterarguments": [
            "Flooding was foreseeable in monsoon geography",
            "Contractor failed to mitigate",
            "LD clause was a genuine pre-estimate",
        ],
        "statutes": ["Indian Contract Act, 1872", "Arbitration and Conciliation Act, 1996"],
        "courts": ["Delhi High Court", "Bombay High Court", "SIAC"],
        "amount_range": (18.0, 85.0),
        "synonyms": {
            "Force majeure": [
                "force majeure",
                "exceptional circumstances",
                "natural disaster defence",
                "contractual impossibility",
                "Act of God clause",
            ],
            "flooding": [
                "flooding",
                "exceptional weather event",
                "extreme rainfall",
                "inundation of the site",
                "monsoon disruption",
            ],
            "liquidated damages": [
                "liquidated damages",
                "LDs",
                "delay damages",
                "pre-agreed compensation for delay",
            ],
        },
        "hidden_keys": ["flooding", "force majeure", "amount", "court"],
        "outcome_pool": ["Partial success", "Award in favour of contractor", "Settled", "Award in favour of employer"],
    },
    "shareholder_oppression": {
        "label": "Minority shareholder oppression",
        "practice_areas": ["Corporate", "Disputes"],
        "matter_types": ["Shareholder Dispute"],
        "facts": [
            "Minority shareholders alleged exclusion from management",
            "Promoter allotted shares to a related entity",
            "Dividend policy was suspended for three years",
            "Board meetings were convened on short notice",
        ],
        "legal_issues": ["Oppression and mismanagement", "Valuation", "Derivative claims", "Related party allotment"],
        "arguments": [
            "Allotment diluted minority without proper valuation",
            "Conduct was burdensome and wrongful",
            "Buy-out at fair value is the appropriate remedy",
        ],
        "counterarguments": [
            "Allotment was for bona fide capital raising",
            "Minority had historically remained passive",
            "NCLT should not rewrite commercial bargains",
        ],
        "statutes": ["Companies Act, 2013"],
        "courts": ["NCLT Mumbai", "NCLT Delhi", "NCLAT"],
        "amount_range": (12.0, 140.0),
        "synonyms": {
            "oppression": ["oppression and mismanagement", "s.241/242 petition", "unfair prejudice", "squeeze-out"],
            "dilution": ["dilution", "share watering", "preferential allotment to affiliates"],
        },
        "hidden_keys": ["allotment", "valuation", "forum"],
        "outcome_pool": ["Buy-out ordered", "Settled", "Petition dismissed", "Partial relief"],
    },
    "spa_indemnity_cap": {
        "label": "SPA indemnity cap negotiation",
        "practice_areas": ["M&A", "Corporate"],
        "matter_types": ["Share Purchase Agreement", "Due Diligence"],
        "facts": [
            "Buyer acquired a controlling stake in a manufacturing company",
            "Tax contingent liabilities surfaced in diligence",
            "Parties negotiated an indemnity cap and escrow",
            "Locked-box accounts were used instead of completion accounts",
        ],
        "legal_issues": ["Indemnity cap", "Locked-box leakage", "W&I insurance", "Material adverse change"],
        "arguments": [
            "Cap should reflect disclosed tax exposure",
            "Escrow better protects against leakage",
            "MAC should exclude industry-wide shocks",
        ],
        "counterarguments": [
            "Seller cannot stand behind unknown historic tax risk indefinitely",
            "W&I is a cleaner residual risk transfer",
        ],
        "statutes": ["Companies Act, 2013", "Income-tax Act, 1961"],
        "courts": ["Bombay High Court"],
        "amount_range": (40.0, 320.0),
        "synonyms": {
            "indemnity cap": ["indemnity cap", "liability ceiling", "seller exposure limit"],
            "locked-box": ["locked-box", "fixed equity value", "no leakage construct"],
        },
        "hidden_keys": ["cap_amount", "escrow", "tax"],
        "outcome_pool": ["Closed", "Aborted", "Renegotiated"],
        "versioned": True,
        "version_clause": "Indemnity",
        "version_values": ["₹10 crore", "₹20 crore", "₹25 crore", "₹20 crore"],
        "version_reason": "Partner requested a lower cap following client negotiation.",
    },
    "loan_security": {
        "label": "Acquisition finance and security enforcement",
        "practice_areas": ["Banking & Finance"],
        "matter_types": ["Loan Agreement", "Facility Agreement", "Security Enforcement", "Debt Restructuring"],
        "facts": [
            "Lenders provided a rupee term loan for acquisition of a target",
            "Security package included share pledge and hypothecation",
            "Borrower missed two consecutive interest payments",
            "Lenders issued a recall notice and considered enforcement",
        ],
        "legal_issues": ["Event of default", "Share pledge enforcement", "SARFAESI overlay", "Intercreditor"],
        "arguments": [
            "Payment default triggered acceleration",
            "Pledge can be enforced without court in terms of the deed",
            "Restructuring is preferable to value-destructive enforcement",
        ],
        "counterarguments": [
            "Default was technical and was cured",
            "Enforcement would violate the standstill in the ICA",
        ],
        "statutes": ["SARFAESI Act, 2002", "Companies Act, 2013", "IBC, 2016"],
        "courts": ["DRT Mumbai", "Bombay High Court"],
        "amount_range": (75.0, 900.0),
        "synonyms": {
            "event of default": ["event of default", "EoD", "acceleration event"],
            "pledge": ["share pledge", "security over promoter shares", "non-disposal undertaking"],
        },
        "hidden_keys": ["missed_payments", "security_package", "amount"],
        "outcome_pool": ["Restructured", "Enforced", "Refinanced", "Settled"],
    },
    "cirp": {
        "label": "Corporate insolvency resolution",
        "practice_areas": ["Insolvency"],
        "matter_types": ["CIRP", "Liquidation", "Personal Guarantee Enforcement"],
        "facts": [
            "Financial creditor filed a Section 7 petition",
            "Corporate debtor disputed the existence of a financial debt",
            "Committee of creditors approved a resolution plan with haircut",
            "Operational creditors challenged distribution",
        ],
        "legal_issues": ["Financial debt", "CoC commercial wisdom", "Fair and equitable treatment", "Personal guarantees"],
        "arguments": [
            "Debt and default are established from the facility documents",
            "CoC's commercial wisdom is largely non-justiciable",
            "Personal guarantors remain independently liable",
        ],
        "counterarguments": [
            "Claim is in the nature of an operational debt",
            "Plan discriminates similarly placed creditors",
        ],
        "statutes": ["Insolvency and Bankruptcy Code, 2016"],
        "courts": ["NCLT Ahmedabad", "NCLT Mumbai", "NCLAT", "Supreme Court of India"],
        "amount_range": (90.0, 1400.0),
        "synonyms": {
            "CIRP": ["CIRP", "corporate insolvency", "Section 7 proceeding", "IBC process"],
            "haircut": ["haircut", "value gap", "recovery percentage"],
        },
        "hidden_keys": ["section", "haircut", "forum"],
        "outcome_pool": ["Plan approved", "Liquidation", "Settled pre-admission", "Appeal pending"],
    },
    "employment_exit": {
        "label": "Senior exit and non-compete",
        "practice_areas": ["Employment"],
        "matter_types": ["Wrongful Termination", "Non-Compete Dispute", "Wage Claim", "POSH Investigation"],
        "facts": [
            "CXO was terminated citing loss of confidence",
            "Employer sought to enforce a 24-month non-compete",
            "Employee claimed unpaid variable compensation",
            "Garden leave was imposed without a contractual basis",
        ],
        "legal_issues": ["Section 27 Contract Act", "Wrongful termination", "Variable pay", "Garden leave"],
        "arguments": [
            "Post-termination non-competes are void as restraint of trade",
            "Variable pay had accrued against published KPIs",
            "Loss of confidence was a pretext",
        ],
        "counterarguments": [
            "Confidentiality and non-solicit remain enforceable",
            "Variable pay was discretionary",
        ],
        "statutes": ["Indian Contract Act, 1872", "Industrial Disputes Act, 1947"],
        "courts": ["Delhi High Court", "Labour Court Bengaluru"],
        "amount_range": (1.2, 18.0),
        "synonyms": {
            "non-compete": ["non-compete", "restraint of trade", "post-employment restriction"],
            "variable pay": ["variable pay", "bonus", "incentive compensation"],
        },
        "hidden_keys": ["noncompete_months", "unpaid_amount", "pretext"],
        "outcome_pool": ["Settled", "Injunction refused", "Partial payment ordered"],
    },
    "title_diligence": {
        "label": "Land title and development agreement",
        "practice_areas": ["Real Estate"],
        "matter_types": ["Title Diligence", "Development Agreement", "Lease Dispute"],
        "facts": [
            "Developer proposed a joint development on peri-urban land",
            "Title chain showed an unregistered family settlement",
            "Part of the land fell in a proposed alignment for a metro corridor",
            "Municipality issued a stop-work notice mid-excavation",
        ],
        "legal_issues": ["Marketable title", "Family settlement", "Public purpose overlay", "RERA registration"],
        "arguments": [
            "Unregistered family settlement does not perfect title",
            "Metro alignment is a material planning risk",
            "Stop-work can be stayed if the notice is procedurally defective",
        ],
        "counterarguments": [
            "Long possession and mutation support marketable title",
            "Alignment is only a proposal",
        ],
        "statutes": ["Transfer of Property Act, 1882", "RERA, 2016", "Registration Act, 1908"],
        "courts": ["Bombay High Court", "Karnataka High Court"],
        "amount_range": (25.0, 400.0),
        "synonyms": {
            "title": ["marketable title", "clean title", "deducible title"],
            "family settlement": ["family settlement", "internal arrangement", "unregistered partition"],
        },
        "hidden_keys": ["metro", "unregistered", "stop_work"],
        "outcome_pool": ["Transaction aborted", "Indemnified close", "Writ pending"],
    },
    "transfer_pricing": {
        "label": "Transfer pricing assessment",
        "practice_areas": ["Tax"],
        "matter_types": ["Transfer Pricing", "GST Dispute", "Assessment Appeal"],
        "facts": [
            "TPO proposed an adjustment on intra-group management fees",
            "Assessee used TNMM with a local comparable set",
            "Revenue alleged that the fees were a sham",
            "DRP confirmed part of the adjustment",
        ],
        "legal_issues": ["Arm's length price", "Benefit test", "Comparables", "Penalty exposure"],
        "arguments": [
            "Services were actually rendered and documented",
            "Comparables must be functionally similar",
            "Penalty is not automatic",
        ],
        "counterarguments": [
            "No tangible benefit was demonstrated",
            "Foreign AE comparables are unreliable",
        ],
        "statutes": ["Income-tax Act, 1961"],
        "courts": ["ITAT Mumbai", "ITAT Delhi", "Bombay High Court"],
        "amount_range": (8.0, 220.0),
        "synonyms": {
            "ALP": ["arm's length price", "ALP", "transfer price"],
            "management fees": ["management fees", "intra-group services", "head office recharge"],
        },
        "hidden_keys": ["method", "adjustment", "forum"],
        "outcome_pool": ["Partly allowed", "Remanded", "Fully allowed", "Dismissed"],
    },
    "sebi_insider": {
        "label": "SEBI insider trading investigation",
        "practice_areas": ["Regulatory"],
        "matter_types": ["SEBI Investigation", "Competition Commission", "Sectoral Licensing"],
        "facts": [
            "SEBI issued a show-cause notice alleging unpublished price sensitive information",
            "Trades were executed days before a board-approved acquisition",
            "Connected persons included a consultant on the diligence team",
            "Firm advised on both the transaction and the regulatory response",
        ],
        "legal_issues": ["UPSI", "Connected person", "Chinese walls", "Settlement regulations"],
        "arguments": [
            "Information had become generally available through rumours and press",
            "Consultant was not a connected person at the trade date",
            "Settlement without admission is appropriate",
        ],
        "counterarguments": [
            "Timing of trades is highly proximate",
            "Chinese walls were undocumented",
        ],
        "statutes": ["SEBI Act, 1992", "PIT Regulations, 2015"],
        "courts": ["SAT", "SEBI Adjudication", "Supreme Court of India"],
        "amount_range": (2.0, 45.0),
        "synonyms": {
            "UPSI": ["UPSI", "unpublished price sensitive information", "inside information"],
            "show-cause": ["show-cause notice", "SCN", "adjudication notice"],
        },
        "hidden_keys": ["trade_timing", "consultant", "settlement"],
        "outcome_pool": ["Settled", "Penalty imposed", "SCN dropped", "Appeal pending"],
        "restricted_bias": True,
    },
    "commercial_arb": {
        "label": "Supply contract arbitration",
        "practice_areas": ["Arbitration", "Disputes"],
        "matter_types": ["Commercial Arbitration", "Commercial Litigation", "Contract Dispute"],
        "facts": [
            "Long-term supply agreement was terminated for alleged quality failures",
            "Buyer withheld the final milestone payment",
            "Seller invoked ICC / SIAC arbitration",
            "Parties disputed whether termination was lawful",
        ],
        "legal_issues": ["Wrongful termination", "Consequential loss", "Quality specifications", "Take-or-pay"],
        "arguments": [
            "Termination was premature and in bad faith",
            "Quality tests were not conducted as prescribed",
            "Withholding the milestone was a separate breach",
        ],
        "counterarguments": [
            "Repeated failures amounted to repudiation",
            "Consequential loss is excluded by contract",
        ],
        "statutes": ["Indian Contract Act, 1872", "Arbitration and Conciliation Act, 1996"],
        "courts": ["SIAC", "ICC", "Bombay High Court"],
        "amount_range": (9.0, 160.0),
        "synonyms": {
            "termination": ["termination", "repudiation", "cancellation of the supply contract"],
            "quality": ["off-spec product", "quality failures", "non-conforming goods"],
        },
        "hidden_keys": ["milestone", "seat", "quality"],
        "outcome_pool": ["Partial award", "Settled", "Seller successful", "Buyer successful"],
    },
    "investment_arb": {
        "label": "Treaty investment claim",
        "practice_areas": ["Arbitration"],
        "matter_types": ["Investment Arbitration"],
        "facts": [
            "Foreign investor alleged expropriation after a licence cancellation",
            "Host state cited environmental non-compliance",
            "Investor invoked a bilateral investment treaty",
            "Quantum includes sunk costs and lost profits",
        ],
        "legal_issues": ["Expropriation", "FET", "Police powers", "Quantum"],
        "arguments": [
            "Cancellation was disproportionate and targeted",
            "FET was breached by inconsistent regulator conduct",
            "Police powers doctrine does not cover disguised expropriation",
        ],
        "counterarguments": [
            "Licence conditions were repeatedly breached",
            "Investor failed to exhaust local remedies",
        ],
        "statutes": ["BIT", "UNCITRAL Arbitration Rules"],
        "courts": ["PCA", "ICSID AF", "Singapore"],
        "amount_range": (120.0, 2100.0),
        "synonyms": {
            "expropriation": ["expropriation", "taking", "licence cancellation as taking"],
            "FET": ["fair and equitable treatment", "FET", "stable legal framework"],
        },
        "hidden_keys": ["licence", "treaty", "quantum"],
        "outcome_pool": ["Jurisdiction upheld", "Claim dismissed", "Partial quantum", "Settled"],
    },
    "jv": {
        "label": "Joint venture deadlock",
        "practice_areas": ["Corporate", "M&A"],
        "matter_types": ["Joint Venture", "Corporate Restructuring", "Merger"],
        "facts": [
            "50:50 JV deadlocked over a capacity expansion",
            "Shareholders' agreement contained a Russian roulette clause",
            "One shareholder alleged deadlock was manufactured",
            "Put/call mechanics were triggered",
        ],
        "legal_issues": ["Deadlock", "Russian roulette", "Good faith", "Valuation of put"],
        "arguments": [
            "Clause is enforceable as a bargained exit",
            "Trigger was in accordance with SHA notice mechanics",
            "Independent valuer should determine fair value",
        ],
        "counterarguments": [
            "Trigger was in bad faith to force a distressed sale",
            "Clause is penal in the circumstances",
        ],
        "statutes": ["Companies Act, 2013", "Indian Contract Act, 1872"],
        "courts": ["Singapore International Commercial Court", "Bombay High Court"],
        "amount_range": (30.0, 500.0),
        "synonyms": {
            "deadlock": ["deadlock", "stalemate", "failure of reserved matters"],
            "russian roulette": ["Russian roulette", "shotgun clause", "buy-sell trigger"],
        },
        "hidden_keys": ["ratio", "clause", "valuation"],
        "outcome_pool": ["Buy-out completed", "Restructured", "Arbitration pending"],
    },
}


def theme_for_matter_type(practice_area: str, matter_type: str) -> str:
    for key, theme in THEMES.items():
        if practice_area in theme["practice_areas"] and matter_type in theme["matter_types"]:
            return key
    # fallback by practice area
    for key, theme in THEMES.items():
        if practice_area in theme["practice_areas"]:
            return key
    return "commercial_arb"


def opposing_name_bank() -> list[str]:
    return [
        "Meridian Engineering Pvt. Ltd.",
        "Northline Construction Co.",
        "Helios Power Ltd.",
        "Cedar Grove Holdings",
        "State Urban Development Authority",
        "Pacific Bulk Commodities",
        "Orion Capital Partners",
        "Vantage Logistics Pvt. Ltd.",
        "Redwood Cement Ltd.",
        "National Highways Concessionaire",
        "Silverline Pharma Ltd.",
        "Kestrel Mining Co.",
        "Harbour View Hotels",
        "Zenith Telecom Infra",
        "Blue Oak Energy",
    ]
