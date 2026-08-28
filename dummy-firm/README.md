# Dummy firm — synthetic knowledge-base universe

Apex Chambers is a **coherent** synthetic law firm. Documents are not random; they are generated from matters, and matters are generated from a shared DNA (facts, issues, arguments, amounts, forums).

## Generation order

`members → clients → matters → matter DNA → documents → relationships → arguments/entities → evaluation questions`

Do not generate documents independently of matters.

## Scale

Configured in `config/firm.yaml`:

| Profile | Members | Clients | Matters | Documents (approx.) |
|---|---|---|---|---|
| `starter` (default) | 20 | 30 | 100 | ~1,000 |
| `v1` | 40 | 50 | 200 | ~4,000–5,000 |
| `v2` | 100 | 500 | 1,000 | ~50,000 |

The same generator and taxonomy are used at every scale. Relationships stay internally consistent.

## Generate

```bash
cd dummy-firm
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_firm.py
python scripts/generate_firm.py --profile v1
```

Outputs land in `data/`:

| File | Contents |
|---|---|
| `members.json` | Lawyers and support staff |
| `clients.json` | Clients, aliases, preferred lawyers, subsidiaries |
| `matters.json` | Matters, teams, codes, status |
| `matter_dna.json` | Ground-truth facts / issues / arguments / amounts |
| `documents.jsonl` | Full text + metadata (including SPA versions) |
| `relationships.jsonl` | same_client, similar_facts, precedent_for, … |
| `arguments.jsonl` | Argument database keyed to matters and docs |
| `entities.jsonl` | PERSON, CLIENT, COURT, STATUTE, LEGAL_ISSUE, mentions |
| `permissions.json` | Restricted matters and allowed members |
| `evaluation.jsonl` | Questions with answer keys (levels 1–7) |
| `summary.json` | Counts |

## What the corpus is designed to test

1. **Exact retrieval** — matter codes, titles  
2. **Semantic retrieval** — “natural disaster” vs “flooding” vs “force majeure”  
3. **Matter / similar-matter retrieval** — shared DNA, different wording  
4. **Person / expertise retrieval** — construction arbitration partners  
5. **Cross-document reasoning** — amount, forum, and weather fact split across docs  
6. **Knowledge-graph retrieval** — same lead, different clients  
7. **Citations / arguments** — argument database  
8. **Permissions** — restricted partner matters  
9. **I don't know / insufficient evidence** — negative topics with empty expected sets  
10. **Versioning** — indemnity cap v1→v2→v3→Final plus a partner note explaining why  

Prose is **template-composed from DNA**, not independently sampled from an LLM, so the answer key remains valid. Entity aliases (`Apex Infra.`, `AIL`, `the Client`) and typos are injected as noise.

## Important rule

If you later add an LLM rewrite step, **rewrite from DNA with a frozen fact sheet**, and keep `matter_dna.json` as the source of truth. Do not let the model invent new parties, amounts, or outcomes.
