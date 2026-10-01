# Grounding roadmap — Ask the Firm + Assistant

Started 2026-09-26. Goal: every sentence a lawyer sees is either backed by a verified source span
that supports it, or explicitly marked as unsupported / not found. No answers from model memory
presented as law.

Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + eval evidence)

## Root causes found (2026-09-26, live DB + code)

| # | Symptom | Root cause | Where |
|---|---|---|---|
| 1 | "Board approved transfer on 12 Sep [1]" cites the "meeting held" sentence | The LLM chooses the quote, and the code only checks that the quote **exists** in the document, never that it **supports** the claim. | `app/chat/verify_citations.py`, `app/chat/system_prompt.py`, `app/chat/agent.py` |
| 2 | Ask the Firm cites at document level | Citations are `(DOC-…)` IDs. The snippet is the first 400 chars of a chunk. The stream is shown before validation, and invented IDs stay in the text. | `app/km/answer.py`, `app/api/hits.py` |
| 3 | `ask_firm` passages cited by the Assistant skip verification | `doc_store` is never filled for them | `app/chat/tools/firm_tools.py` |
| 4 | CERC question answered from model memory, and wrong (describes the repealed 2010 PoC regime) | The prompt says "answer from legal knowledge", and there is no public-law corpus (0 chunks) | `app/chat/system_prompt.py`, corpus |
| 5 | Clarifying questions asked on a clear query | The `ask_inputs` rule has no ambiguity gate | `app/chat/system_prompt.py` |
| 6 | Section titles `eeting`, `SCLOSURE SCHEDULE` (25 docs) | The heading regex's Roman-numeral class runs with IGNORECASE | `app/documents/canonical.py` |
| 7 | "Ereement — CTO"; the next turn's opening appended to the previous answer | Stream assembly (not yet reproduced) | chat SSE / `ChatPage.tsx` |
| 8 | Same model (`zai.glm-5`) for everything, never benchmarked for citation discipline | Configuration | `.env`, `app/config.py` |

## Acceptance gates (measured by `evals/grounding_eval.py` over live HTTP)

- Citation precision (cited span entails the claim): **≥ 0.97**
- Unsupported claims shown to the user without a flag: **≤ 1%**
- Parametric leak on statutory / regulatory questions: **0**
- Abstention recall on unanswerable questions: **≥ 0.95**
- `pytest tests/` green; retrieval gate (`evals/gate.py`) not regressed

## Pass 1: WS0 + WS1 + WS2 (2026-09-27) — results in `docs/experiments/grounding_2026-09-27.md`

- [x] WS0 grounding eval harness (`evals/grounding_eval.py`), gold set (41 Qs), independent judge, hand calibration (23/24)
- [x] WS1 heading regex fix (`canonical.py`) + reindex of 75 affected docs (5 version-less test docs left)
- [x] WS1 `SECTION ` noise gone from passages (headings now parse as heading blocks; the DOCX body still stores the marker)
- [x] WS1 "answer from legal knowledge" rule removed; `ask_inputs` only for real ambiguity; false-premise rule
- [x] WS1 `ask_firm` passages load the full document into `doc_store` → every chat citation is verified
- [x] WS1 Ask the Firm: invented / unseen-document citations can no longer reach the lawyer (every sentence re-verified)
- [x] WS1 generator 400 "Unterminated string" retried once
- [x] WS2 `app/grounding`: sentence units → candidate spans → element-mapped verdict (Kimi K2.5) → figures guard →
      heading guard → absence check on full documents → answer rewritten with verified `[n]` spans; fail closed
- [x] WS2 unsupported / contradicted sentences removed server-side and reported; partial shown flagged
- [x] WS2 Assistant: final text shown only after verification (`text_final`); Ask the Firm: "verifying" phase
- [x] WS2 UI: Ask `[n]` span chips → Inspector shows the verified quotes; chat cards show all quotes + "Partly supported"
- [ ] WS2 document viewer highlights by server offsets (`start_char`/`end_char`) instead of re-searching quote text
- [ ] Gate: shown-as-supported precision ≥ 0.97 on **both** surfaces (Assistant 0.975–0.980 ✓; Ask 0.92–0.95 ✗)
- [ ] Gold set to 150+ questions incl. multi-matter, long PDFs, tables; second human calibration pass

### Open issues found in pass 1
- [ ] Ask the Firm record-only sentences (matter card) are weaker than document-cited ones; show record quotes as
      citations and require element mapping to non-header record lines
- [ ] Semantic mis-mapping (e.g. "LOA for 199.5 MW" mapped to a 199.5 MW margin sentence) — consensus experiment (v4)
- [ ] Latency: +8–12 s Ask, +15–18 s Assistant at p50 → smaller pools, per-document span cache, parallel calls
- [ ] Absence statements: judge counts them as unsupported; add an eval category and a gold check of their truth
- [ ] Unscoped Ask the Firm still passes weak "candidate matters" (UNSC matter for a CERC query) to the generator
- [ ] Legacy 36k fixed-window chunks: no section/page metadata → weaker spans for PCIJ/UNSC documents

## Pass 2+: tracked next steps

### WS4 — Source curation + user-supplied collections (next)
- [ ] "Collections": document sets not tied to a matter (firm-wide / team / personal ACL), e.g. "CERC
      Regulations" or a client data room. Uses the existing ingest pipeline.
- [ ] A curation record per source: official URL, issuer, instrument, notification date, in-force date,
      amendment chain, checksum, curator, verified flag.
- [ ] Only curated + verified sources may be quoted as statutory text.
- [ ] Statute/regulation-aware parser: regulation / sub-regulation / clause / proviso / schedule paths
      (`Reg 5(3)(c)`), cited at provision level.
- [ ] Assistant: scope to an uploaded collection ("answer only from these documents"), in the style of
      Harvey Vault and Legora.
- [ ] Seed: CERC (Sharing of Inter-State Transmission Charges and Losses) Regs 2020 + amendments,
      CERC GNA Regs 2022, CERC Tariff Regs 2024, Electricity Act 2003 (official PDFs).
- [ ] Remove or replace the unanswerable suggested question in `frontend/src/pages/AskPage.tsx`,
      `HomePage.tsx` until the seed is loaded.
- [ ] Version awareness: the answer states which version / amendment of the instrument it applied.

### WS3 — Query analyser + router
- [ ] Structured analysis (LLM JSON, temperature 0, cached): intent, scope (matter / client / public law /
      firm-wide / collection), jurisdiction, authority, instrument, provisions, answer shape,
      false-premise check.
- [ ] Route "components of transmission charges as per CERC" → public-law collection,
      instrument = Sharing Regs 2020.
- [ ] False premise ("arguments filed" in a transaction) → answer the premise explicitly first.
- [ ] Router classification test set in `tests/`.

### WS5 — Experiments (record each in `docs/experiments/`)
- [ ] Generator model: glm-5 / kimi-k2.5 / gpt-5.6-luna / deepseek-v3.2 (+ Claude if enabled on Bedrock)
- [ ] Citation strategy: prose + block vs structured claims vs extract-then-write
- [ ] Verifier: deterministic only vs + NLI cross-encoder (licence audit) vs + LLM judge
- [ ] Chunk granularity: current chunks vs clause/sentence units
- [ ] Embeddings: MiniLM-384 vs Titan-1024 on public-law + matter queries
- [ ] Legacy corpus: 36k fixed-window chunks have no section/page metadata; re-chunk structurally

### WS6 — Multi-document (tabular) review
- [ ] Fix grounding holes in `app/review/tabular_service.py` (falls back to other documents' hits and to
      `chunk_ids[:2]`)
- [ ] Per-document retrieval only; the WS2 verifier on every cell; "not found in this document" as a value
- [ ] Human override audit trail
- [ ] Grid UI (clean-room; design from requirements only), after WS2 meets the gates
