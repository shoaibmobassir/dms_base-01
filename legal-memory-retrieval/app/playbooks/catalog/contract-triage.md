---
title: Contract triage and risk classification
summary: Identify what a contract is, its key commercial terms, and where it departs from a market position, with suggested redlines.
kind: instructions
practice_area: Commercial
language: English
---
You are triaging one contract for a lawyer.

1. **Before you start**, make sure you know which document to review. If the user has not attached or named one, ask for it with ask_inputs. Ask which party the firm acts for if it is not clear from the conversation.
2. **Read the whole contract** with read_document (use get_outline first for long documents).
3. **Classify it**: the type of contract, its purpose, the parties and their roles.
4. **Key commercial terms**: duration and renewal, termination rights (for convenience and for cause, with notice periods), payment terms.
5. **Risk matrix** — for each, quote the clause and say whether it is favourable, neutral or unfavourable to the firm's client:
   - indemnities (capped or uncapped, who gives them)
   - limitation of liability and carve-outs (fraud, wilful misconduct, confidentiality, IP)
   - restrictive covenants, exclusivity, non-compete
   - IP ownership and licences
   - governing law, jurisdiction and dispute resolution
6. **Deviations**: list where the contract departs from a balanced market position and propose redlines with propose_edits (Word documents only; for PDFs, describe the change).

Keep the result short and in a table where it helps. Every statement must cite the clause it relies on.
