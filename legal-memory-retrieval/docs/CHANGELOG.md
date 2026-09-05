# Changelog

Metrics come from `python evals/retrieval_eval.py` on frozen `evals/dataset.jsonl` (n=445).

## 2026-09-05 — P5.6-C7.4b/C7.5 phrase·proximity·soft role + CE evidence

**Question:** Do phrase/proximity + stronger soft role lift evidence recall? Does CE-on-evidence help once gold is in the pool?

**Freeze held:** CE for **document** ranking / GraphRAG / production flags OFF.

### Code
- `app/retrieval/evidence.py` — phrase + proximity channels, hybrid lexical RRF, multiplicative soft role (×2.5 preferred / ×0.7 ANALYSIS)
- `app/retrieval/evidence_rerank.py` — proposition↔passage CE (ablation only)
- Gold: densest span per gold doc + offsets (`evals/build_gold_evidence.py`)
- Ablation: `evals/evidence_retrieval_ablation.py` → `evals/last_evidence_retrieval.*`

### Evidence metrics (n=7)

| Variant | Ev R@20 | Hit@20 | Ev R@100 | MRR |
| ------- | ------: | -----: | -------: | --: |
| lexical + strong soft role | **.033** | .357 | .072 | .190 |
| phrase | .026 | .214 | .065 | .021 |
| proximity | .000 | .000 | .000 | .000 |
| hybrid_lexical RRF | .026 | .214 | .065 | .021 |
| lexical + hard role (diag) | **.055** | **.714** | .168 | .242 |
| vector_raw / ctx | ~0 | ~0 | ~0 | ~0 |
| **ce_soft** | .005 | .071 | .065 | .040 |
| **ce_hard_role** | .024 | .357 | .168 | .087 |

C7.4 soft ref R@20=.020 → soft lexical **.033** (modest). Soft Hit@20 .21→**.36**.

### Learning
1. Stronger soft role helps a little; **hard family scope still dominates** Hit@20.
2. Phrase ≈ OR; proximity channel empty / unused on this corpus.
3. **C7.5 FAIL:** ms-marco CE on proposition+passage **hurts** ranking (hard Hit@20 .71→.36). Same topic-bias failure mode as doc CE — do **not** enable evidence CE in production.
4. Candidate **generation/ranking** remains the bottleneck; CE cannot invent missing gold.

### Gate
Soft Ev R@20 still **not material** (<.20). `ce_production=false`, `graphrag_next=false`.  
**Next:** C7.6 evidence→document aggregation on best **non-CE** channel (soft lexical / hard-role diagnostic); improve candidate pool (title/header fields, structured entities) — **not** more CE variants.

## 2026-09-05 — P5.6-C7 evidence-first baseline (C7.0–C7.4)

**Pivot:** Documents are containers; retrieve **evidence spans** against **propositions**.

**Freeze held:** CE for doc ranking / GraphRAG / production flags OFF.

### Code / data
- Schema: `app/retrieval/proposition.py`, `app/retrieval/evidence.py`
- Curated: `evals/propositions.jsonl` (7 semantic queries, 8 propositions)
- Gold bootstrap: `evals/build_gold_evidence.py` → `evals/gold_evidence.jsonl`
- Ablation: `evals/evidence_retrieval_ablation.py` → `evals/last_evidence_retrieval.*`
- Tests: `tests/test_proposition_evidence.py` (8 pass)

### Evidence metrics (primary; n=7 queries, avg over props)

| Variant | Ev R@20 | Hit@20 | Ev R@100 | MRR |
| ------- | ------: | -----: | -------: | --: |
| lexical (soft role) | .020 | .214 | .060 | .048 |
| **lexical + hard role (deep pool)** | **.070** | **.714** | .156 | .227 |
| vector_raw / vector_ctx | .000 | .000 | ~.007 | ~0 |
| hybrid_rrf (soft) | .000 | .000 | .046 | .009 |
| hybrid + hard role | .025 | .357 | .160 | .065 |

Secondary doc-from-hybrid R@20 **.021** (D5 doc R@20 ref **.043**).

### Diagnosis
- Gold chunks are **in theme** and **FTS-matchable**; failure is **ranking**, not scope.
- Claim-token OR pollution buried gold; curated `lexical_terms` only.
- Soft role prior insufficient; deep-pool + hard family lifts Hit@20 .21→**.71** (same lesson as D5).
- Proposition→chunk vectors still **Case C** (topic memos dominate).
- Bootstrap gold = whole gold-doc chunks (often EL/ICA); not yet precise evidence spans.

### Gate
Soft-path Ev R@20 **not material** (<.20). Do **not** open CE/GraphRAG.  
**Next:** phrase/proximity evidence candidates + stronger role prior; refine gold spans; then C7.5 CE-on-evidence only if pool Hit is high.

## 2026-09-05 — P5.6-C5.5-D6 purpose profiling (no lift beyond role)

**Question:** Does document purpose add information beyond role family?

**Freeze held:** CE/GraphRAG/flags off; oracle only.

### Code
- `app/retrieval/doc_purpose.py` — purpose taxonomy, title/header/opening signals, purpose cards
- Ablation: `evals/purpose_profile_ablation.py` → `evals/last_purpose_profile.{json,md}`
- Dataset: `evals/purpose_hardneg_dataset.jsonl`

### Ceilings
| Scope | Ceiling | Avg docs |
| ----- | ------: | -------: |
| Theme / Role family / **Purpose** | **1.00 / 1.00 / 1.00** | role=purpose=**855** |
| Type EL/ICA | 0.83 | — |

Family→purpose reduction **1.0×** (oracle multi-purpose recreates family).

### Retrieval
| Variant | R@20 | Hit@20 |
| ------- | ---: | -----: |
| D5/D6-A family+lex | .043 | .571 |
| D6-B purpose+lex | **.043** | **.571** |
| D6-C purpose+ctx | .014 | .286 |

### Learning
Purpose is **not** a new discriminative routing layer here — coextensive with role family under gold oracles; no R@20 gain.  
**Next:** proposition/evidence-level retrieval inside theme (+ soft role prior). Stop deeper document classification.

## 2026-09-05 — P5.6-C5.5-D4/D5 role-family oracle

**Question:** Is role-family the right constraint, and does oracle role scope recover document retrieval?

**Freeze held:** CE/GraphRAG/fusion off; oracle only (no production hard filter).

### Code
- `doc_profile.py` — `role_family` taxonomy, `oracle_role_families_from_gold`, type→family map
- Ablation: `evals/role_family_oracle_ablation.py` → `evals/last_role_family_oracle.{json,md}`

### D4 ceilings (n=7)
| Scope | Ceiling | Avg docs |
| ----- | ------: | -------: |
| Theme | **1.000** | 3465 |
| **Role family (oracle)** | **1.000** | **855** (~4.3× smaller) |
| Type EL/ICA | 0.829 | — |

Q-0273 oracle families = `PLEADING`+`ANALYSIS`+`EVIDENCE_RECORD` (multi-family).  
Q-0271 `TRANSACTIONAL` includes Term Sheet → typed_ceil gap closed.

### D5 R@20 (oracle hard scope)
| Variant | R@20 | Hit@20 | R@100 |
| ------- | ---: | -----: | ----: |
| theme raw | .000 | .000 | .007 |
| family + ctx | .014 | .286 | .136 |
| **family + lexical** | **.043** | **.571** | **.164** |

### Learning
- **Role family is the correct routing primitive** (ceiling 1.0).
- Role conditioning helps (**Hit@20 .57**) but R@20 still ≪ .30 → need **within-family** purpose/content signal.
- Production role routing must stay **soft** (prioritize + fallback), never hard-exclude until a real classifier exists.

## 2026-09-05 — P5.6-C5.5-D document profile discovery (D0–D3)

**Question:** What features separate gold docs from Research Memo / Opinion / Strategy *inside the same theme*?

**Freeze held:** theme routing, C5.4 lexical, C5.5 ctx embeds; CE/GraphRAG off.

### Code
- `app/retrieval/doc_profile.py` — cheap features, `document_role`, log-odds table
- Ablation: `evals/doc_profile_discovery.py` → `evals/last_doc_profile_discovery.{json,md}`
- Dataset: `evals/gold_vs_hardneg_dataset.jsonl`

### D3 typed ceiling (.829)
- **B_benchmark_problem**, not mislabeled EL/ICA.
- Q-0271: 4× Term Sheet (`PRIMARY_AGREEMENT`).
- Q-0273: **typed_ceil=0** — gold is Research Memo / Statement of Claim / Hearing Notes only.

### D2 top signals (gold vs confuser types)
| Feature | P(gold) | P(neg) | log_odds |
| ------- | ------: | -----: | -------: |
| is_el_ica / role_engagement | .829 | .000 | **8.5** |
| engagement / assessment header | .40–.43 | .000 | **6.5** |
| role_strategy / opinion_header | .000 | .22–.27 | **−5.6** |
| longer body / citations | lower | higher | weak topical |

Signature / shall / defined-terms = **0** on both sides (short synthetic templates).

### Learning
Discriminative signal is **document genre/role**, not topic. EL/ICA-only filters cannot be final (lose flood + some JV). Next: **D4/D5 type/role oracle** retrieval with role families.

## 2026-09-05 — P5.6-C5.5 contextual chunk embeddings (Case C)

**Question:** Given correct theme scope, can contextual chunk vectors (title+type+section+text) put gold docs in top-20/50?

**Freeze held:** C5.4-D lexical baseline; CE/GraphRAG/fusion off; query = raw question only.

### Code
- `app/retrieval/contextual_embed.py` — contextual text format, max/top3/top5 aggregation, gold margins
- `scripts/embed_contextual.py` — fills `chunks.embedding_ctx` (does not touch `embedding`)
- Ablation: `evals/contextual_chunk_ablation.py` → `evals/last_contextual_chunk.{json,md}`
- Embedded **26,735** theme-scoped chunks (`ctx_chunk_v1`)

### Results (n=7 semantic)

| Variant | R@20 | R@100 | Hit@100 | avg best-gold |
| ------- | ---: | ----: | ------: | ------------: |
| C5.4-D frozen | .007 | — | .429 | ~147 |
| raw_max (control) | .000 | .007 | .143 | ~248 |
| **A1 ctx+max** | **.000** | **.000** | **.000** | ~163 |
| A2 / A3 | .000 | .000 | .000 | ~211 |

### Diagnosis
- Top-20 dominated by Legal Opinion / Research Memo / Strategy Notes (**topic**, not holder docs).
- Gold EL/ICA chunk sims ~0.40–0.52 but **below** top non-gold; aggregation does not help.
- **Case C:** representation still cannot find gold at R@100.

### Gate
Do not enable contextual lane. Next: inspect what distinguishes gold EL/ICA from Research Memos (content/labels), not more MiniLM prefixing / not CE.

## 2026-09-05 — P5.6-C5.4 discriminative lexical (negative at R@20)

**Question:** Can field-weighted / phrase / concept / EL·ICA-prior lexical ranking surface gold docs inside the correct theme?

**Freeze held:** theme routing, CE, vector, GraphRAG, `THEME_SCOPED_DOCUMENT_RETRIEVAL=off`.

### Code
- `app/retrieval/disc_lexical.py` — in-theme DF buckets, field weights, phrase/concept lanes, soft EL/ICA prior
- Ablation: `evals/disc_lexical_ablation.py` → `evals/last_disc_lexical.{json,md}`
- Alias: `THEME_SCOPED_DOCUMENT_RETRIEVAL` (+ legacy `THEME_SCOPED_DOCUMENT_RESOLVE`)

### Results (n=7 semantic)

| Variant | R@20 | Hit@20 | R@100 | Hit@100 | MRR | avg best-gold |
| ------- | ---: | -----: | ----: | ------: | --: | ------------: |
| A OR-BM25 | .007 | .143 | .036 | .143 | .026 | ~166 |
| B disc fields | .000 | .000 | .021 | .143 | .004 | ~209 |
| C + phrase/concept | .007 | .143 | .057 | .286 | .025 | ~175 |
| **D + EL/ICA prior** | **.007** | **.143** | **.086** | **.429** | **.030** | **~147** |

Typed ceiling (EL+ICA) avg **.829** (not 1.0 — flood/JV golds include other types).

### Diagnosis
- Token buckets work (e.g. drop `information`/`price`; keep `SCN`/`insider`).
- **Non-gold Research Memos dominate** top ranks (high phrase+concept on title/body).
- Many **gold EL/ICA rows are missing or mid-pack** once ultra-common OR terms are removed — they only matched the broad C5.1 OR via high-DF tokens.
- D improves Hit@100 / best-rank slightly but **does not move R@20**.

### Gate
`d_materially_above_a` = **False**. Do **not** enable theme-scoped retrieval.  
**Next: C5.5 contextual document embeddings** (title + type + section/chunk context), not more BM25 tuning / not CE.

## 2026-09-05 — P5.6-C5 theme-complete document resolution

**Question:** Once theme routing is correct, can BM25 / vector find gold **documents** inside the theme?

**Freeze held:** P5.5 + P5.6-A; `THEME_SCOPED_DOCUMENT_RESOLVE=off`; no CE; no GraphRAG.

### Code
- `app/retrieval/theme_scoped.py` — theme resolver + doc RRF + SRR (`THEME_SCOPED_DOCUMENT_RESOLVE`, default off)
- Ablation: `evals/theme_scoped_doc_ablation.py` → `evals/last_theme_scoped_doc.{json,md}`
- Tests: `tests/test_theme_scoped.py`

### Results (n=7 semantic, max_themes=1)

| Stage | R@20 | Hit@20 | R@50 | R@100 | notes |
| ----- | ---: | -----: | ---: | ----: | ----- |
| **C5.0 ceiling** | — | — | — | — | **1.000** (all gold docs ∈ theme) |
| C5.1 BM25 OR | .007 | .143 | .007 | .036 | gold often match but ranks ~100–300 |
| C5.2 Vector | .000 | .000 | .000 | .007 | best gold often ≫500 / absent |
| C5.3 Union RRF | .000 | .000 | .007 | .029 | no rescue |

**Scope:** avg **93 matters → 3,465 docs**, SRR **~11.5×** (corpus 38,250 → theme).

**Per-query BM25 best-gold rank (top-500):** Q-0273=6 (only Hit@20); others 118–286 or missing.

### Diagnosis
- **Theme is a sufficient routing boundary for recall ceiling** (C5.0 PASS).
- **Naive OR-BM25 is not discriminative inside theme** — almost all theme docs match broad OR terms; gold Engagement Letter / ICA pairs sit mid-pack.
- **Chunk-vector remains a bad document selector** even with theme scope + 8k chunk pool (same failure mode as C0/B0 at doc level).
- Gate **FAIL** for enabling resolve / CE (`union R@20 ≪ .85`).

### Next (per roadmap, no graph)
1. Lexical upgrade inside theme: phrase/concept-weighted FTS, title/body field weights, drop ultra-common OR tokens, optional EL+ICA type prior.
2. If still weak → contextual document embeddings (title + section + chunk).
3. Only then CE. Keep escape-hatch / multi-theme N=1..3 for later.

## 2026-09-05 — P5.6-C4 matter evidence profiles

**Diagnosis (before building):** holders are **scattered within theme** (med rank ~50, p90 ~114 under C1). Within a `theme_key`, holders and non-holders share identical `legal_issues` — field weights cannot separate them.

### Code
- `app/retrieval/matter_profile.py` — theme inference, doc-type intent, field-weighted `score_matter_profile`
- `PgMatterStore.fetch_evidence_profiles` — parties/types + optional in-matter doc BM25
- Ablation: `evals/matter_profile_ablation.py` → `evals/last_matter_profile_ablation.{json,md}`

### Results (n=7 semantic)

| Variant | Cov@20 | Cov@50 | Cov@100 | MRR | % reach Cov≥0.9 |
| ------- | -----: | -----: | ------: | --: | --------------: |
| C1 lexical_struct | .248 | .557 | .871 | .40 | 71% |
| **C4 theme** | .219 | **.600** | **.986** | **.46** | **100%** |
| C4 profile / doctype | .205 | .543 | .843 | .33 | 86% |
| C4 + doc evidence | .248 | .452 | .814 | .32 | 71% |

### Learning
- **Theme routing is the C4 win** — once the query maps to `theme_key`, nearly all holders are in the pool by K≈|theme| (~60–113).
- Cov@50 **cannot** reach .90 on this corpus without within-theme discrimination that metadata does not provide (expected ≈ K/|theme|).
- Doc-type / in-matter BM25 did **not** beat theme for coverage (gold docs are Engagement Letter + ICA pairs, not distinctive clause text).

### Gate
`SEMANTIC_DOC_RESOLVE` stays **off** (Cov@50 .60 < .90).  
**Next:** C5 with **theme-complete scope** (all matters in matched `theme_key`, not top-50 rank cut) — Doc ceiling = 1.0 when theme is correct.

## 2026-09-05 — P5.6-C1 holder-matter resolution (lexical wins)

**Question:** Can we get *holder* matters (matters containing gold docs) into top-K?

**Freeze held:** P5.5 + P5.6-A; `SEMANTIC_DOC_RESOLVE=off`; no CE changes.

### Code
- `app/retrieval/matter_resolver.py` — structured query rep, OR tsquery, RRF, HolderCoverage@K
- `PgMatterStore.search_lexical_or` — weighted FTS over title/practice/theme/legal_issues/facts
- Ablation: `evals/holder_matter_ablation.py` → `evals/last_holder_matter_ablation.{json,md}`

### HolderCoverage@K (n=7 semantic; ~3–10 holders/query)

| Variant | Cov@20 | Cov@50 | Cov@100 | Hit@20 | % reach Cov≥0.9 |
| ------- | -----: | -----: | ------: | -----: | --------------: |
| vector (C0) | .100 | .100 | .100 | .57 | **0%** |
| **lexical_struct** | **.248** | **.557** | **.871** | **1.00** | **71%** (avg min K≈75) |
| lexical | .219 | .543 | .871 | .86 | 71% |
| hybrid_struct | .186 | .538 | .886 | .71 | 71% |
| vector_struct | .129 | .129 | .129 | .57 | 0% |

### Learning
- Chunk-vector matter routing **stalls** at Cov≈.10 — confirms C0.
- **OR lexical on matter metadata** is the first signal that finds holders (Cov@50 crosses .50).
- Hybrid RRF does not beat pure lexical yet (vector still pollutes mid ranks).
- Still short of Cov@20≥.50 / production routing K≤50 — next: matter evidence profiles (C4) + lexical ranking, then retry C5 doc resolve.

## 2026-09-05 — P5.6-C0 semantic matter→doc routing (negative result)

**Question:** Can vector-retrieved matters act as a reliable document routing layer?

**Harness:** `evals/semantic_doc_resolve_ablation.py` → `evals/last_semantic_doc_resolve.{json,md}`  
Helpers: `app/retrieval/semantic_resolve.py` (`SEMANTIC_DOC_RESOLVE=c0` reserved; **not enabled**).

### Ablation (n=7 semantic)

| Matter K | Matter Hit@K | Matter Precision@K | Doc ceiling | Doc R@20 | Avg docs in scope |
| -------: | -----------: | -----------------: | ----------: | -------: | ----------------: |
| 5 | **1.0** | **1.0** | .029 | .014 | 188 |
| 10 | **1.0** | **1.0** | .057 | .000 | 379 |
| 20 | **1.0** | **1.0** | .100 | .000 | 654 |
| 50 | **1.0** | **1.0** | .100 | .000 | 685 |

Baseline open-vector Doc R@20 remains **0**.

### Diagnosis

- Vector top-K matters are **always gold matters** (precision 1.0) — theme discovery works.
- But gold **documents** live in only **~3–10 holder matters** per query; those holders are **mostly absent** from the vector matter neighborhood (often 0/10 in top-300).
- Oracle “all labeled gold matters” → Doc ceiling **1.0**; vector-routed subset ceiling stalls at **≤0.10**.
- Therefore C0 alone cannot unlock Doc R@20 — need better **matter ranking toward document-holding matters** (query rep / paraphrases / contextual or matter-level embeddings), then re-try routing.

**Do not enable `SEMANTIC_DOC_RESOLVE` yet. Do not touch CE.** Next: C1 OR-BM25 and/or C2 query representation aimed at holder-matter recall.

## 2026-09-05 — P5.6-B0 semantic candidate survival (diagnosis only)

**Freeze held:** `MATTER_SCOPE=hard` + `p55_repair_ce_protect` (no matter-routing / fusion / embed changes).

**Harness:** `evals/semantic_candidate_survival.py` → `evals/last_semantic_survival.{json,md}`  
Unit: `tests/test_semantic_survival.py`

### Document-level R@20 (n=7 semantic, 20 gold docs each)

| Stage | R@20 | Hit@20 |
| ----- | ---: | -----: |
| BM25 / Vector / Union / Fusion / CE / Final | **0.0** | **0.0** |

**Outcome: A — candidate generation.** Do **not** touch CE.

### Matter-level (theme clusters, 59–113 gold matters)

| Stage | Matter R@20 | Matter Hit@20 |
| ----- | ----------: | ------------: |
| Vector | .191 | **1.0** |
| Union | .207 | **1.0** |
| Fusion | .111 | 1.0 |
| CE | .212 | 1.0 |
| Final | .126 | 1.0 |

### Deep-pool probe (limit 500, not in default pipeline)

- All 20×7 gold **docs are embedded**
- BM25 often returns **0** rows (AND-heavy `plainto_tsquery` on long legal phrases)
- Vector@500: still **0 gold docs**; but hits **many gold matters**
- Matter channel: rare gold docs only deep (e.g. rank 47–99)

**Implication for P5.6-C:** fix query/chunk representation and BM25 or-query / concept expansion so **gold documents enter the pool**. Vector already finds the right *matters* — document selection inside those matters is the gap. Matter routing untouched.

## 2026-09-05 — P5.6-A matter routing (scope ≠ score) — ablation recorded

**P5.5 freeze held** until hard-scope evidence channel was fixed. **Promoted default:** `MATTER_SCOPE=hard` (still `p55_repair_ce_protect` + exact-title).

### Code
- `app/retrieval/matter_scope.py` — `MATTER_SCOPE=off|score|hard|hier`; hard/hier only for `matter_research` / `experience_search`
- `PgMatterStore.resolve_matters` + `documents_in_matters` (**one head/matter**) + `matter_scope` channel
- BM25/vector `filters.matter_ids`; matter RRF weight **0** under hard/hier; `matter_scope` weight **1.2**
- Ablation: `evals/matter_routing_ablation.py`

### Ablation (n=445) vs P5.5 FINAL (.739 / .926 / .805)

| Var | Mode | R@10 | Hit@10 | MRR | matter Hit@10 | Exact | Promote? |
|-----|------|-----:|-------:|----:|--------------:|------:|----------|
| A | off (P5.5) | .739 | .929 | .807 | .725 | .996 | — |
| B | score boost | .754–.756 | .941–.946 | .831–.836 | .85–.90 | .996 | yes (score path) |
| C₀ | hard (no heads) | .723↓ | .865↓ | .795↓ | .075↓ | .996 | no |
| **C** | **hard + matter_scope heads** | **.764** | **.948** | **.859** | **.875** | **.996** | **YES** (+2.5/+2.2/+5.4pp) |
| D | hier only | .707↓ | .818↓ | .731↓ | .525 | .996 | no |
| E/F | hier hybrid | ≤.744 | ≤.921 | ~.807 | ≤.675 | .996 | no |

**CRR:** ~4.4 matters → ~174 docs avg under hard scope.

**Learning:** Resolution was already correct; failure mode was deleting matter evidence when weight→0. One head/matter as `matter_scope` + in-scope BM25/vector fixes that. Prefer **C (hard scope)** over B (score) — same gate, better architecture. Semantic/similar still ~0 — tracks 6.2–6.3 next. Hier hybrid not ready.

## 2026-09-05 — P5.5 exact retrieval repair (+ CE-protect frozen)

**Root cause:** exact queries (`What is the matter code for …?`, n=220) used unordered metadata catalog hits (`score=1.0`), so duplicate titles / later `DOC-37xxx` buried gold `DOC-000xx`.

### Fix
- `PgMetadataStore._exact_title_search` — title-match quality + `document_id` ASC
- Exact planner: metadata weight **3.0**, BM25 **0.5**, no CE/graph
- Default policy frozen to **`p55_repair_ce_protect`**
- Taxonomy: `evals/exact_failure_taxonomy.py` → `evals/last_exact_taxonomy.json`

### Eval (n=445)

| | CE-protect | **+ exact fix** | pre-P5.3 baseline |
|--|----------:|----------------:|------------------:|
| R@5 | .522 | **.675** | .402 |
| R@10 | .621 | **.739** | .590 |
| Hit@10 | .803 | **.926** | .924 |
| MRR | .627 | **.805** | .694 |
| nDCG@10 | .604 | **.759** | .557 |

- **Overall gate (R@10 ∧ Hit@10 ∧ MRR ≥ baseline): PASS**
- **Exact:** R@10/Hit@10/MRR **.9955** (was ~.77); taxonomy 219/220 HIT, 1× duplicate-title miss
- Next: matter/semantic/similar_matter (exact frozen)

## 2026-09-05 — P5.5 pipeline repair (hierarchy ≠ ranking)

**Diagnosis-driven:** gold was found then destroyed in fusion/CE — not a “need more channels” problem.

### Code
- **P5.5.1** Removed matter/doc stage-score blend into chunk score (`PgHierarchicalStore`) — hierarchy is WHERE to search only
- **P5.5.2–3** `app/retrieval/fusion_policy.py` — named policies; default `p55_repair`: hierarchical RRF weight **0**, matter **0.5**, graph **0.3**; metadata/BM25/vector ~1.0–1.2; exact_lookup planner weights untouched
- **Gen budgets** kept at 50 (wide gen@100 **hurt** Hit@10)
- **CE protection** implemented but **off** by default (`p55_repair_ce_protect` for later)
- **Ablation CLI:** `evals/retrieval_ablation.py` / `FUSION_POLICY=...`

### Eval (n=445) vs pre-P5.3 baseline / P5.3

| policy | R@5 | R@10 | Hit@10 | MRR | nDCG@10 |
|--------|----:|-----:|-------:|----:|--------:|
| baseline | .402 | .590 | **.924** | **.694** | .557 |
| p53 | .503 | .592 | .772 | .600 | .570 |
| **p55_repair** | **.507** | **.598** | **.789** | **.601** | **.573** |
| p55_no_hier_channel | .503 | .587 | .764 | .596 | .565 |
| p55_wide_gen | .462 | .558 | .730 | .558 | .534 |

- Gate (R@10 ∧ Hit@10 ∧ MRR ≥ baseline): **FAIL** (Hit@10/MRR still short)
- vs P5.3: modest **Hit@10 +1.7pp**, **MRR +0.1pp**, **R@10 +0.6pp** — directionally correct, not production-ready
- Next: P5.5.6–8 inspect CE drop cases + CE context enrichment (do not add channels)

## 2026-09-05 — P5.4d diagnosis tooling (no fusion changes)

- **Instrument:** `app/retrieval/diagnose.py` — per-candidate channel ranks/scores, RRF rank, hierarchical channel rank, reranker/final ranks, relevance flags
- **CLI:** `evals/retrieval_diagnose.py` → `evals/last_retrieval_diagnose.csv` + `last_retrieval_diagnose_summary.json`
- **Question answered:** at which stage do relevant docs drop out of top-10 (`fusion_or_hierarchy_channel` vs `reranker` vs `final_topk_cutoff`)
- **First run** (103 queries: cross_document + graph_reasoning + matter_retrieval + negative):
  - Drop stages among relevant candidates pushed out of top-10: **reranker 236**, **fusion_or_hierarchy_channel 115**
  - Relevant channel combos dominated by `metadata` / `graph_seed` alone — hierarchy rarely sole source of gold
  - graph_reasoning MRR **0.16**, matter_retrieval Hit@10 **0.43** — ranking broken; cross_document Hit@10 still 1.0 on this slice but MRR/Recall@10 still weak in full eval
  - Negatives need a separate false-positive report (empty gold makes Hit@10/MRR uninformative)
- **Policy:** no weight/planner/LLM changes in this slice — observation only before P5.5 fusion correction
- **Gates:** Hit@10 + MRR required alongside Recall@10 (see plan Phase 5)

## 2026-09-05 — P5.3 hierarchical Matter→Document→Chunk channel

- **Store:** `PgHierarchicalStore` — ACL-aware cascade: rank matters → documents → prefer version-scoped child chunks (`version_id` + `is_parent=FALSE`), legacy fallback
- **Engine v2:** `hierarchical` channel registered; planner enables it for `cross_document` / `semantic` / `similar_matter` / default research (not exact lookup)
- **Review:** when `query_text` is set, prune candidate docs/blocks via hierarchical retrieve before Map
- **Contracts:** Candidate metadata carries `version_id` / `section_id` / `folder_path` / `block_ids`; provenance `hierarchical_score`
- **Fix:** `retrieve_async` auto-`init_pool()` so CLI eval / sync wrappers do not silently return empty hits
- **Tests:** `tests/test_hierarchical_retrieval.py`
- **Eval (n=445)** vs prior `last_retrieval_run` (Recall@10 **0.5895**):
  - Overall Recall@10 **0.5920** (+0.0025) — gate **PASS** on overall R@10 only
  - Recall@5 **0.5025** (+0.1004); nDCG@10 **0.5698** (+0.0130)
  - **Regressions:** Hit@10 **0.7715** (−0.1523); MRR **0.5998** (−0.0943); Recall@20 **0.6421** (−0.0493)
  - By type R@10: exact **0.7576** (+0.1076); cross_document **0.3232** (−0.1594); graph_reasoning **0.1146** (−0.3354); matter_retrieval **0.1983** (−0.1352); negatives **0.75** (−0.25)
  - **Do not claim a retrieval quality win** beyond the tiny overall R@10 delta; hierarchical fusion weights need tuning before P5.5 is green

## 2026-09-05 — FirmOS tasks 6+8: Page→Section→Block + version chunks

- **Extractors:** page-aware PDF (`\f` page joins); DOCX via `python-docx` (MIT); unified `extract_from_bytes`
- **Blocks:** `parse_canonical_blocks(..., page_spans=)` uses real page numbers; list/table/md section types
- **Hierarchical chunks:** parent (section) + child chunks per **version**; `folder_path` / `section_*` / `page_number` / `block_ids` / `parent_chunk_id`
- **Context envelope:** `GET /api/documents/chunks/{id}/context` + `HierarchicalChunk.context_envelope`
- **Wire:** `create_version` + upload batch persist blocks+chunks; migration `scripts/migrate_version_chunks.py`
- **Tests:** `tests/test_structure_and_version_chunks.py` (19 related tests green)

## 2026-09-05 — FirmOS Immediate Next (object store + upload batches)

- **Domain models:** `app/domain/models.py` — Tenant→…→Version→Finding/Evidence/Annotation
- **Object store:** `app/storage/object_store.py` — local default; optional MinIO/S3 (`OBJECT_STORE_BACKEND=s3`); deterministic keys `tenant/client/matter/doc/versions/vNNN/original.ext`
- **Upload batches:** `upload_batches` / `upload_batch_files`; `POST /api/uploads/batches` + `/run`; folder paths preserved; per-file failure isolation
- **Compose:** `docker compose --profile object-store up` for MinIO
- **Tests:** `tests/test_firmos_upload_batch.py`
- Plan checkboxes updated in repo-root `firmos_production_actionable_plan.md` (Immediate Next 1–5,7,9–10)

## 2026-09-05 — Document Intelligence + Version Control (Phase 0–2 slice)

- **Plan:** `docs/plan/13_document_intelligence_version_control.md` — phased breakable tasks (P0–P8).
- **Migration:** `scripts/migrate_doc_intelligence.py` applies blocks, diffs, review_jobs, findings, evidence_anchors, annotations, `document_intelligence`; adds `parent_version_id` / `storage_uri` / `change_summary` on versions.
- **Wiring:** `create_version` sets parent lineage + auto-persists canonical blocks; version list returns timeline fields; `POST .../resolve-anchor` for durable content anchors.
- **Tests:** 23 unit tests green (parser, anchors, semantic diff, versioning, review engine). No retrieval eval change this slice.

## 2026-09-03 — Engine v2 live wiring + e2e fixes + Ask debug UI

- **Live path:** `app.retrieval.engine.retrieve` delegates to `engine_v2` when `use_engine_v2=true` (default). `/api/retrieval` and `/api/answers` now run planner + parallel channels (incl. vector) with no lexical→vector sequencing.
- **Fixes:** exact_lookup fusion no longer uses `rerank_candidates=0`; Postgres `ILIKE … ESCAPE` corrected; BM25/metadata use cleaned `search_text`; matter channel free-text fallback; understand strips `have we previously advised on` / `what matters involve`.
- **UI:** Ask retrieval debug panel (`/ui/ask?debug=1`), Architecture view (`/ui/architecture`), `GET /api/system/architecture` + enriched `/health`/`/info` (engine v2 flags).
- **Doc Search:** companion docs on `:8001` — `POST /debug`, `/docs-ui`, `ARCHITECTURE.md` (avoids port clash with LEXOS).
- **E2E (live DB):** force majeure → bm25+vector hits; Narang → bm25/metadata/matter; `MTR-2020-00463` → 5 metadata hits; graph reasoning → seed+expansion; ask returns cited answer.
- **Tests:** `pytest tests/` green. Retrieval quality eval not re-run in this change (wiring/UI only).

## 2026-08-23 — Sprint 2: lexical baseline

- **Channels:** keyword (Postgres FTS) + metadata
- **Recall@10:** 0.4073
- **MRR:** 0.3593
- **nDCG@10:** 0.3492
- semantic / similar_matter / graph_reasoning / person_expertise / matter_retrieval: ~0
- negative, permission: ~1.0
- Files: schema, ingest, FTS, eval harness, `POST /retrieve`

## 2026-08-23 — Sprint 3: MiniLM + pgvector (infra shipped; overall gate not met)

Embedder: local `sentence-transformers/all-MiniLM-L6-v2` (384-d, L2-normalized). 41,788 chunks embedded. HNSW cosine index on `chunks.embedding`. ACL identical to FTS. `RETRIEVAL_CHANNELS` selects `keyword`, `metadata`, `vector`, `graph`. Default remains `keyword,metadata` so vector ANN does not pollute negatives.

### Vector-only

- **Recall@10:** 0.2638 (below lexical 0.4073 — **gate fail** on overall)
- **MRR:** 0.3096
- **nDCG@10:** 0.2272
- matter_retrieval Recall@10: 0.20 (was 0)
- person_expertise Recall@10: 0.11 (was 0)
- similar_matter Recall@10: 0.008 (was 0)
- semantic Recall@10: 0.0 (gold sets are entire theme clusters; Recall@10 is capped at 10/|gold|)
- negative Recall@10: 0.0 (ANN always returns neighbors — expected)
- permission Recall@10: 0.5 (DENIED half still holds; AUTHORIZED exact-id questions are weak for MiniLM)

### Hybrid preview (not default)

`keyword,metadata,vector` RRF: Recall@10 **0.3973** (slightly under lexical), MRR **0.4184** (above lexical 0.359). exact Recall@10 0.42 vs lexical 0.37. Negatives still collapse if vector is on.

### Files

- `app/embeddings/minilm.py`, `scripts/embed.py`, `app/retrieval/semantic.py`, `app/retrieval/engine.py`
- Durable memory: `.cursor/skills/legal-memory/`, `docs/NORTH_STAR.md`, `.cursor/rules/legal-memory.mdc`

## 2026-08-23 — Sprint 4: hybrid RRF + routing (gate passed)

Default channels: `keyword,metadata,vector`. Weighted RRF (metadata 1.5, keyword 1.2, vector 0.75). Skip vector on exact matter-id/code lookups. Drop ANN hits with cosine < 0.42; if FTS+metadata are empty, require cosine ≥ 0.50 so negatives abstain.

### Hybrid (now default)

- **Recall@10:** 0.4343 (**beats lexical 0.4073 and vector-only 0.2638**)
- **Hit@10:** 0.7076
- **MRR:** 0.3853
- **nDCG@10:** 0.3666
- exact Recall@10: 0.3879
- negative: 1.0 (restored)
- permission: 1.0
- matter_retrieval: 0.20 (Hit@10 0.60)
- semantic / similar_matter Recall@10: still 0
- Files: `app/retrieval/route.py`, weighted fusion, engine routing, eval `hit@10`

## 2026-08-23 — Sprint 5: cross-encoder rerank (gate passed)

Local `cross-encoder/ms-marco-MiniLM-L-6-v2` on fused top 100. Blend CE (0.55) with min-max RRF (0.45). Skip rerank when the query contains an explicit `MTR-` id (preserves permission 1.0). Eval still requests k=20 so Recall@20 is comparable.

### Hybrid + rerank (now default)

- **Recall@10:** 0.4723 (**beats hybrid 0.4343**)
- **Recall@20:** 0.6140 (**beats hybrid 0.5898** — gold not dropped)
- **Hit@10:** 0.8059 (was 0.7076)
- **MRR:** 0.4882 (was 0.3853)
- **nDCG@10:** 0.4105 (was 0.3666)
- exact Recall@10: 0.4652 (was 0.3879)
- negative: 1.0
- permission: 1.0
- semantic / similar_matter / graph_reasoning Recall@10: still 0
- Files: `app/retrieval/reranker.py`, engine fuse→rerank, `tests/test_reranker.py`

## 2026-08-23 — Sprint 6: query understanding (gate passed)

Rule-based intent + entity parse (no LLM). Strip boilerplate so metadata ILIKE hits titles/clients. Route experience questions onto practice area. Skip vector on ids/codes. `/health` exposes `sprint` + feature flags. `POST /retrieve` returns `understanding`.

### Hybrid + rerank + understanding (now default)

- **Recall@10:** 0.5391 (**beats rerank 0.4723**)
- **Recall@20:** 0.6245 (**beats rerank 0.6140**)
- **Hit@10:** 0.7985 (was 0.8059)
- **MRR:** 0.6082 (was 0.4882)
- **nDCG@10:** 0.4972 (was 0.4105)
- exact Recall@10: 0.6682 (was 0.4652)
- matter_retrieval: 0.3008 (was 0.2545)
- person_expertise: 0.1714 (was 0.0095)
- negative: 1.0
- permission: 1.0
- cross_document Recall@10: 0.0187 (was 0.4732 — **regression**; matter-code queries skip vector. Sprint 7 candidate.)
- semantic / similar_matter / graph_reasoning Recall@10: still ~0
- Files: `app/query/understand.py`, `app/sprint.py`, engine routing, `tests/test_understand.py`, `tests/test_retrieval_edges.py`, `tests/test_health.py`

## 2026-08-24 — Sprint 7: SQL matter graph (gate passed on who/which-matter)

Postgres `relationships` + same-lead/different-client via `matter_members`. Default channels add `graph`. Long queries that only contain a matter *code* keep vector. `graph_reasoning` skips metadata so the seed matter does not bury related matters. API keys in `.env` only; answer LLM still off.

### Hybrid + rerank + understanding + graph (now default)

- **Recall@10:** 0.5539 (**beats Sprint 6 0.5391**)
- **Recall@20:** 0.6570 (**beats 0.6245**)
- **Hit@10:** 0.8329 (was 0.7985)
- **MRR:** 0.6263 (was 0.6082)
- **nDCG@10:** 0.5141 (was 0.4972)
- graph_reasoning Recall@10: 0.4223 (was 0.0); Hit@10 0.9333
- person_expertise: 0.1905 (was 0.1714)
- exact: 0.6682 (held)
- negative / permission: 1.0
- cross_document Recall@10: 0.0219 (**not restored** vs Sprint 5 0.47)
- Files: `app/retrieval/graph.py`, engine graph channel, `app/sprint.py`

## 2026-08-24 — Cross-document restore (pre–Sprint 8)

Long “position … MATTER-CODE” questions are `cross_document`. Keyword/vector stay on the raw question; metadata ranks chunks inside the matter by `ts_rank_cd` instead of dumping the first 50. Rerank is not skipped.

### Hybrid + rerank + understanding + graph (still default)

- **Recall@10:** 0.5889 (**beats Sprint 7 0.5539**)
- **Recall@20:** 0.6922 (**beats 0.6570**)
- **Hit@10:** 0.9189 (was 0.8329)
- **MRR:** 0.6930 (was 0.6263)
- **nDCG@10:** 0.5561 (was 0.5141)
- cross_document Recall@10: 0.4826 (was 0.0219; Sprint 5 was 0.47)
- exact: 0.6561 (was 0.6682)
- graph_reasoning: 0.4223 (held)
- negative / permission: 1.0

## 2026-08-24 — Sprint 8: answers + citations + abstention

`POST /ask` retrieves first, then answers. Citations must be retrieved `DOC-` ids; hallucinated ids are dropped and the call abstains. Empty retrieval abstains (`no_evidence`) without calling an LLM. Named `MTR-`/`DOC-` lookups abstain if that entity is not in the ACL-filtered hits. Groq (then Gemini) when keys exist; extractive snippets otherwise. Retrieval eval is unchanged.

- Answer eval (extractive): abstention accuracy **1.0** on negatives + DENIED (n=38); citation grounding **1.0** on 40 exact questions (cited ⊆ retrieved).
- Files: `app/answers/*`, `POST /ask`, `evals/answer_eval.py`, `tests/test_answers.py`

### Next gate (Sprint 9)

Redis cache + latency. Do not add Kafka/Neo4j/agents.

## 2026-08-28 — Section routes: one API prefix per sidebar view

Replaced catch-all `/api/browse` and `/api/institutional` with dedicated section routers aligned to the LEXOS sidebar. Each document is served at `/api/documents/{document_id}` with sub-routes for versions, diff, and chunks.

- **home** `/api/home` — dashboard stats
- **matters** `/api/matters` — list, detail, arguments, related, timeline, graph
- **documents** `/api/documents` — list, `{id}`, ingest, versions, diff, chunks
- **clients** `/api/clients` — list, detail, matters
- **people** `/api/people` — directory
- **projects** `/api/projects` — workstreams (unchanged prefix)
- **teams** `/api/teams`, **knowledge** `/api/knowledge`, **activity** `/api/activity`, **tasks** `/api/tasks`
- **search** `/api/search` — command palette
- **answers** `/api/answers`, **retrieval** `/api/retrieval`, **system** `/api/system`
- Files: `app/api/routers/{matters,documents_router,clients,people,...}.py`, `static/app.js`, `tests/test_api_services.py`

## 2026-08-28 — API gateway: service-oriented routes

Monolithic flat routes removed. Six bounded services mounted under `/api/{service}` matching the LEXOS frontend. No retrieval ranking changes — eval rerun not required.

- **system** `/api/system` — health, metrics, info
- **retrieval** `/api/retrieval` — hybrid search with ACL
- **answers** `/api/answers` — grounded Q&A with citations
- **browse** `/api/browse` — members, clients, matters, documents, search, ingest, versions, diff, timeline, graph *(superseded by section routes above)*
- **projects** `/api/projects` — workstreams and milestones
- **institutional** `/api/institutional` — stats, knowledge, activity, tasks, teams *(superseded)*
- Files: `app/api/main.py` (gateway), `app/api/routers/*`, `app/api/documents.py`, `app/api/hits.py`, `tests/test_api_services.py`

## 2026-08-30 — Sprint 9: DMS Answer Quality + Parallel Retrieval

### Phase 1: Production Ingest Pipeline

Built `app/ingest/` — reusable, resumable, idempotent PDF ingest pipeline.

- `app/db/schema.sql` — Additive extensions: `source_uri`, `content_sha256`, `mime_type`, `ingest_job_id`, `ingested_at` on `documents`; new `ingest_jobs` + `ingest_items` tables
- `app/ingest/models.py` — `DocumentRecord`, `IngestItem`, `IngestJob`, `MatterManifest`
- `app/ingest/extractors/pdf.py` — pypdf-based text extraction
- `app/ingest/normalize.py` — filename → document_type inference + manifest matching
- `app/ingest/writer.py` — INSERT with `content_sha256` idempotency
- `app/ingest/pipeline.py` — Orchestrator: extract → normalize → chunk → write
- `app/ingest/jobs.py` — Job lifecycle: create, register, mark, complete, resume
- `app/ingest/cli.py` — `python -m app.ingest run --source ../docs --manifest ingest/manifests/real_filings.yaml`
- `ingest/manifests/real_filings.yaml` — 3 matter clusters × 7 PDFs

### Phase 2: DMS Gold Eval Dataset

- `evals/dms_portal_dataset.jsonl` — 20 Q&A pairs (factual 8, procedural 4, cross-doc 3, negative 3, metadata 2)
- `evals/dms_answer_eval.py` — Automated eval: retrieval_recall, answer_contains, abstention_accuracy, matter_match, grounding, DMS field presence

### Phase 3: DMS Portal Response Format

`/api/answers` now returns DMS-portal-style structured fields:
- `key_finding` — 1-2 sentence executive summary
- `structured_citations[]` — document_id + matter_id + tags
- `sources[]` — top hits with highlighted snippets
- `matchedMatters[]` — deduplicated by matter_id, ranked by score
- `tags[]` — Matter ID, Document Type, Client, Forum, Practice Area

Files: `app/answers/format.py` (NEW), `app/api/routers/answers.py`, `app/answers/llm.py` (richer prompt + 1200-char context)

### Phase 4: Parallel Retrieval

**Before**: `understand(2×) → keyword → metadata → vector → graph → fusion → rerank`
**After**: `understand(1×) → [keyword | metadata | graph] parallel → vector → fusion → rerank`

- `app/retrieval/engine.py` — `ThreadPoolExecutor` with per-channel DB connections
- `app/answers/generate.py` — Eliminated redundant `understand()` call
- Reports `parallel_wall_ms` in latency breakdown

### Phase 5: Tests

| File | Cases |
|------|-------|
| `tests/test_ingest_pipeline.py` | Doc type inference, manifest matching, title normalization, sha skip |
| `tests/test_parallel_retrieval.py` | Channel parsing, weight adjustments, parallel_wall_ms, cache hit |
| `tests/test_answer_format.py` | Tag building, structured citations, matchedMatters dedup, key_finding |
| `tests/test_ingest_jobs_api.py` | Create job, poll status |
| `tests/test_dms_eval.py` | Dataset schema validation |
| `tests/test_api_services.py` | DMS fields on `/api/answers` |

### Eval results (2026-08-30 run)

**Retrieval** (`evals/retrieval_eval.py`, n=445): Recall@10 **0.5895** (unchanged gate), MRR **0.6941**, nDCG@10 **0.5568**

**Answer regression** (`evals/answer_eval.py`): abstention accuracy **1.0** (n=38), citation grounding **1.0** (n=40)

**DMS portal** (`evals/dms_answer_eval.py`, n=20, real PDFs seeded):
- Real PDF ingest: **6/7 indexed** (116 new chunks embedded); 1 failed — `MSEDCL Note in APL. 163 of 2018.pdf` (scanned, 0 chars via pypdf)
- retrieval_recall **0.50**, answer_contains **0.375**, abstention_accuracy **0.55**, matter_match **0.3125**, grounding **1.0**
- DMS field presence: key_finding **0.40**, structured_citations **0.55**, tags **0.55**
- avg_latency_ms **1329**

**Dependencies added:** `pypdf` (BSD-3-Clause), `PyYAML` (MIT) — recorded in `docs/legal/DEPENDENCY_AUDIT.md`

**New scripts:** `scripts/migrate_ingest_schema.py`, `scripts/seed_real_docs.py`, `evals/build_dms_eval.py`

## 2026-09-01 — Project Workspace UI (Folders + Version History + Activity)

Frontend wiring for the project improvement sprint. Mike consulted at product level only (AGPL clean-room).

### Project Detail Workspace

- **Overview tab** — scope, milestones (live toggle), team preview, recent documents from API
- **Documents tab** — nested folder tree sidebar, document table with folder move dropdown, version chip → history viewer with diff
- **Activity tab** — chronological audit trail from `project_activity`
- **Export** — one-click JSON manifest download with SHA-256 hashes
- **Inspector pane** — recent activity feed + Ask Project AI

### Bug Fix

- `POST /projects/{id}/documents/{doc_id}` cross-matter copy: fixed broken `cur.execute().fetchone()` chain

### Files Changed

- `static/app.js` — `ensureProjectDetail()`, tab rendering, folder CRUD, version history panel
- `static/styles.css` — folder tree, activity timeline, project workspace layout
- `app/api/routers/projects.py` — assign-document copy fix

## 2026-09-01 — Projects Improvement: Versioning + Folders + Activity

Inspired by Mike product research (AGPL clean-room — see `agpl-cleanroom.mdc`). All designs independently derived from requirements.

### Document Versioning

Immutable `document_versions` table with SHA-256 integrity. Each edit creates a new version row; `documents.current_version_id` points to the active one. Old versions never deleted — full audit trail.

- `app/documents/__init__.py` (NEW) — `create_version()`, `list_versions()`, `get_version()`, `diff_versions()`, `seed_initial_version()`, `content_sha256()`
- `app/api/routers/documents_router.py` — New endpoints: `POST /{id}/versions`, `GET /{id}/versions`, `GET /{id}/versions/{vid}`, `GET /{id}/versions/{vid}/diff`
- `app/db/schema.sql` — `document_versions` table, `current_version_id` + `folder_id` + `updated_at` columns on `documents`

### Project Folders

Nested folder tree with cycle detection (max depth 5). Documents assignable to folders.

- `app/db/schema.sql` — `project_folders` table with `parent_folder_id`
- `app/api/routers/projects.py` — Endpoints: `POST /{id}/folders`, `GET /{id}/directory`, `PATCH /{id}/folders/{fid}`, `DELETE /{id}/folders/{fid}`

### Document Assignment & Copy

- `POST /projects/{id}/documents/{doc_id}` — assign doc to project's matter, or cross-matter copy
- `PATCH /projects/{id}/documents/{doc_id}/folder` — move doc to a folder within the project

### Project Activity Timeline

`project_activity` table records all mutations: project creation, milestone toggles, folder CRUD, document additions/moves.

- `app/projects/__init__.py` (NEW) — `record_activity()` helper with cursor/conn/standalone modes
- `GET /projects/{id}/activity` — paginated timeline with actor names

### Enhanced Project Detail + Export

`GET /projects/{id}` now returns: `team[]`, `folders[]`, `recent_activity[]`, `document_count`

`GET /projects/{id}/export` — downloadable manifest with document list, version hashes, milestones, manifest SHA-256

### New Pydantic Schemas

`FolderCreate`, `FolderUpdate`, `DocumentFolderMove`, `VersionCreate` in `app/api/schemas.py`

### Tests (24/24)

| File | Cases |
|------|-------|
| `tests/test_document_versioning.py` | SHA-256, diff (changes, identical, missing), unicode |
| `tests/test_project_folders.py` | Cycle detection (direct + indirect), depth limit, payload builder, Pydantic schemas |
| `tests/test_project_activity.py` | Activity recording (cursor, conn, standalone), metadata serialization |


