# Plan 20 — Legal research (design doc §22)

Started 2026-10-02. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + eval evidence)

Design: `docs/plan/assistant-design.md` Rev 2.3, Part II (§22). Evals: `evals/research/research_eval.py`
(provider level, no LLM) and `evals/research/research_live.py` (HTTP, research mode).

## Scorecard (§22.1)

| | Today (before) | After R1-local | Target after B, R2, R3 |
|---|---|---|---|
| Total /10 | 1.6 | **6.0** | 7.4 |

## R1-local — authorities the firm holds

- [x] 2026-10-02 caselaw: a failed CourtListener lookup is never a verification; treatment always unknown
      (tests R13 in `tests/test_integrated_mike_features.py`)
- [x] 2026-10-02 citation parser: PCIJ, ICJ, UNSC, UNTS, India, US (parser recall 1.00 on 30 forms)
- [x] 2026-10-02 passage roles: UNSC headnote/preamble/operative; PCIJ majority/dissent/separate opinion
- [x] 2026-10-02 binding rules in `app/research/legal_systems.yaml` (23/23 labels)
- [x] 2026-10-02 local provider: search (graph-gated), resolve, read, citing, derived status
- [x] 2026-10-02 formatter; OCR-tolerant quote location for cite-check
- [x] 2026-10-02 assistant tools + research rules and method in the system prompt; today's date in the prompt
- [x] 2026-10-02 eval: 58 issue questions, 23 binding items, planted errors; live HTTP check (0 fabricated)
- [ ] Post-generation pass: flag or strip citations in the final answer that do not verify (§22.9 hard rule)
- [ ] Grounding: keep headings and table header rows (currently removed as unsupported)
- [ ] Atomic DocIndex alias allocation, then mark research tools parallel-safe (Phase B)
- [ ] Search latency: profile the 2.9 s p50 (cross-encoder over 4×limit passages, body fetches)
- [ ] Retrieval misses: *Nationality Decrees* (B 4), Lockerbie (731/748)
- [ ] Lawyer review of `legal_systems.yaml` (`reviewed_by` is empty)
- [ ] Rebuild the SPA bundle (`static/`) for the new step details (`MessageParts.tsx`)

## R2 — public-source ingestion

- [ ] R0 first: list official sources and terms (ICJ, UN Charter, UNTS, India Code, CERC/APTEL/SC orders)
- [ ] Ingest Indian electricity law (Act, regulations, APTEL/SC/CERC orders) as typed authorities
- [ ] `find_in_authority`; evidence-backed notes (needs Phase B)

## Log

- **2026-10-02** Rev 2.3 of the design doc (phase reorder, local-first research, legal-system models,
  scorecard). Built R1-local on branch `research-authority-layer`. Research eval: R@5 0.64 → 0.97,
  MRR 0.52 → 0.89; all five gates pass after fixing four bugs the eval found (anchored lookup, Chapter VII
  variants, form-feed paragraphs, year-less S/RES). Live research-mode run: first pass exposed a missing
  current date and grounding removing labels; after fixes, 0 fabricated citations in 36, expected authority
  cited 5/5. Decision record: `docs/experiments/legal_research_r1_local_2026-10-02.md`.
