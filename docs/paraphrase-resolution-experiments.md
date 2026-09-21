# Paraphrase Resolution Experiments

**Date:** 2026-09-14  
**Status (2026-09-14 evening):** The table below is the pre-containment baseline. Wrapped-title paraphrases (`Papers we filed in {title}`) now resolve at 1.0 via title-in-query matching. The open gap is a description that never contains the title. Do not re-run vector or fusion experiments against the old 0.4692 number.

**Critical Problem:** Paraphrase queries fail matter resolution (R@10 46.92%, resolved 0%), blocking argument channel

---

## Problem Statement

### The Bottleneck

```
Exact Match Path (✅):
"Acme Corp v. State Bank" → Matter Resolver → MAT-0231 → Argument Channel Arms → R@10 100%

Paraphrase Path (❌):
"What was the case involving Acme's dispute with the bank?" 
  → Matter Resolver → UNRESOLVED 
  → Argument Channel BLOCKED 
  → R@10 46.92%
```

### Current Performance

| Query Type | n | R@10 | Hit@10 | Matter Resolved |
|------------|---|------|--------|-----------------|
| Matter title/code | 170/34 | 1.0000 | 1.0000 | 1.0 ✅ |
| **Paraphrase** | **40** | **0.4692** | **0.6750** | **0.0** ❌ |
| Document name | 40 | 0.9500 | 0.9500 | 0.0 |
| Client name | 21 | 0.7917 | 1.0000 | 1.0 |

**Target:** Paraphrase R@10 ≥ 0.85, Matter Resolved ≥ 0.70

---

## Root Cause Analysis

### Hypothesis Chain

**H1:** Current resolver uses exact/fuzzy string matching only  
**H2:** Resolver runs before retrieval, not after  
**H3:** No semantic matter resolution exists  
**H4:** No matter resolution from retrieved documents  

---

## Phase 1: Diagnostic Experiments (Week 1)

### Experiment 1.1: Matter Resolver Autopsy

**Goal:** Understand current resolver logic and failure modes

**Steps:**

1. **Trace a paraphrase query end-to-end**

```python
# Add to app/retrieval/matter_resolver.py or wherever resolve_matters lives
import logging
logger = logging.getLogger(__name__)

async def resolve_matters_instrumented(
    conn, 
    query: str, 
    member_id: str | None, 
    limit: int = 20
) -> list[dict]:
    """Instrumented version that logs decision points."""
    
    logger.info(f"[Matter Resolver] Input query: {query}")
    
    # Try exact match
    exact_matches = await _resolve_exact(conn, query, member_id)
    if exact_matches:
        logger.info(f"[Matter Resolver] Exact match: {len(exact_matches)} matters")
        return exact_matches
    
    # Try fuzzy match
    fuzzy_matches = await _resolve_fuzzy(conn, query, member_id, threshold=0.8)
    if fuzzy_matches:
        logger.info(f"[Matter Resolver] Fuzzy match: {len(fuzzy_matches)} matters")
        return fuzzy_matches
    
    # Try pattern extraction (matter codes, entity names)
    extracted = _extract_matter_signals(query)
    if extracted["matter_codes"]:
        logger.info(f"[Matter Resolver] Found codes: {extracted['matter_codes']}")
        return await _resolve_by_code(conn, extracted["matter_codes"])
    
    logger.warning(f"[Matter Resolver] FAILED to resolve: {query}")
    return []
```

2. **Run on paraphrase holdout and collect traces**

```bash
# Run eval with instrumentation
python -m app.evals.run_eval \
  --eval-file evals/independent_search.jsonl \
  --gold-file evals/independent_gold.jsonl \
  --filter-type paraphrase \
  --log-level DEBUG \
  --output traces/paraphrase_resolution.jsonl
```

3. **Analyze failure patterns**

```python
# Analysis script: scripts/analyze_resolution_failures.py
import json
from collections import Counter

failures = []
with open("traces/paraphrase_resolution.jsonl") as f:
    for line in f:
        record = json.loads(line)
        if not record["matter_resolved"]:
            failures.append({
                "query": record["query"],
                "expected_matter": record["gold_matter_id"],
                "retrieved_docs": record.get("top_5_docs", []),
                "failure_reason": record.get("resolver_log", "unknown")
            })

# Categorize failures
patterns = Counter()
for f in failures:
    query = f["query"].lower()
    if "case" in query or "matter" in query:
        patterns["indirect_reference"] += 1
    elif any(party in query for party in ["involving", "between", "dispute"]):
        patterns["party_description"] += 1
    elif "where" in query or "that" in query:
        patterns["clause_wrapped"] += 1
    else:
        patterns["other"] += 1

print("Failure patterns:")
for pattern, count in patterns.most_common():
    print(f"  {pattern}: {count}")
```

**Expected Output:**
- List of 40 paraphrase failures with categorization
- Confirmation of hypothesis (exact/fuzzy only, no semantic)

**Success Criteria:**
- ✅ Identify top 3 failure patterns
- ✅ Confirm resolver runs before retrieval
- ✅ Document current matching logic

---

### Experiment 1.2: Retrieval Quality Without Matter Scope

**Hypothesis:** Even without matter resolution, retrieval finds relevant documents

**Test:**

```python
# Evaluate retrieval quality for paraphrases WITHOUT matter scope
async def eval_paraphrase_retrieval_unscoped():
    results = []
    
    for query_record in load_paraphrase_queries():
        query = query_record["query"]
        gold_matter = query_record["gold_matter_id"]
        gold_docs = query_record["gold_doc_ids"]
        
        # Retrieve WITHOUT matter scope
        with connect() as conn:
            hits, _ = retrieve(conn, query, member_id=None, k=20)
        
        # Check if retrieved docs are from the right matter
        retrieved_matters = set(h.get("matter_id") for h in hits)
        correct_matter_in_top_k = gold_matter in retrieved_matters
        
        # Check document recall
        retrieved_doc_ids = set(h.get("document_id") for h in hits[:20])
        recall_at_20 = len(retrieved_doc_ids & set(gold_docs)) / len(gold_docs)
        
        results.append({
            "query": query,
            "gold_matter": gold_matter,
            "retrieved_matters": list(retrieved_matters),
            "correct_matter_in_top_20": correct_matter_in_top_k,
            "recall_at_20": recall_at_20,
        })
    
    return results

# Metrics
correct_matter_rate = sum(r["correct_matter_in_top_20"] for r in results) / len(results)
avg_recall = sum(r["recall_at_20"] for r in results) / len(results)

print(f"Correct matter in top-20 hits: {correct_matter_rate * 100:.1f}%")
print(f"Document recall@20: {avg_recall * 100:.1f}%")
```

**Expected Findings:**
- Retrieval likely finds correct matter docs (70-80% in top-20)
- But resolver can't identify the matter from the query text
- **Key insight:** Problem is query→matter mapping, not retrieval quality

**Success Criteria:**
- ✅ Quantify "retrieval gets it, resolver doesn't" gap
- ✅ Confirm retrieval is NOT the bottleneck

---

## Phase 2: Semantic Matter Resolution (Week 2-3)

### Experiment 2.1: Vector-Based Matter Resolver

**Hypothesis:** Semantic similarity can map paraphrases to matters

**Architecture:**

```
Paraphrase Query
    ↓
Embed Query (MiniLM)
    ↓
Vector Search Against Matter Profiles
    ↓
Top-K Matters by Similarity
    ↓
Confidence Threshold (0.7)
    ↓
Resolved Matters
```

**Implementation:**

```python
# File: app/retrieval/matter_resolver_v2.py

import numpy as np
from app.embeddings.minilm import MiniLMEmbedder

class VectorMatterResolver:
    """Semantic matter resolution via vector similarity."""
    
    def __init__(self):
        self.embedder = MiniLMEmbedder()
        self._matter_embeddings: dict[str, np.ndarray] = {}
        self._matter_profiles: dict[str, str] = {}
    
    async def build_matter_index(self, conn):
        """Pre-compute embeddings for all matter profiles."""
        
        # Fetch matter metadata
        rows = await conn.execute("""
            SELECT 
                m.matter_id,
                m.matter_code,
                m.title,
                m.client_name,
                m.opposing_party,
                m.practice_area,
                array_to_string(m.legal_issues, ', ') AS legal_issues,
                array_to_string(m.facts, '. ') AS facts
            FROM matters m
        """).fetchall()
        
        # Build textual profiles
        profiles = []
        matter_ids = []
        
        for row in rows:
            profile = f"""
Matter: {row['title']}
Code: {row['matter_code']}
Client: {row['client_name']}
Opposing Party: {row.get('opposing_party', 'N/A')}
Practice Area: {row['practice_area']}
Legal Issues: {row.get('legal_issues', 'N/A')}
Key Facts: {row.get('facts', 'N/A')}
            """.strip()
            
            self._matter_profiles[row['matter_id']] = profile
            profiles.append(profile)
            matter_ids.append(row['matter_id'])
        
        # Embed all profiles
        logger.info(f"Embedding {len(profiles)} matter profiles...")
        embeddings = self.embedder.encode(profiles)
        
        for matter_id, emb in zip(matter_ids, embeddings):
            self._matter_embeddings[matter_id] = emb
        
        logger.info(f"Matter index ready: {len(self._matter_embeddings)} matters")
    
    async def resolve(
        self, 
        query: str, 
        top_k: int = 5, 
        threshold: float = 0.70
    ) -> list[dict]:
        """Resolve query to matters via semantic similarity."""
        
        if not self._matter_embeddings:
            logger.warning("Matter index not built, cannot resolve")
            return []
        
        # Embed query
        query_vec = self.embedder.encode([query])[0]
        
        # Compute similarities
        similarities = []
        for matter_id, matter_vec in self._matter_embeddings.items():
            # Cosine similarity
            sim = np.dot(query_vec, matter_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(matter_vec)
            )
            similarities.append((matter_id, float(sim)))
        
        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Filter by threshold
        resolved = [
            {"matter_id": mid, "confidence": sim}
            for mid, sim in similarities[:top_k]
            if sim >= threshold
        ]
        
        logger.info(
            f"Resolved {len(resolved)} matters for query: {query[:50]}... "
            f"(top sim: {similarities[0][1]:.3f})"
        )
        
        return resolved

# Singleton
_vector_resolver: VectorMatterResolver | None = None

async def get_vector_resolver(conn) -> VectorMatterResolver:
    global _vector_resolver
    if _vector_resolver is None:
        _vector_resolver = VectorMatterResolver()
        await _vector_resolver.build_matter_index(conn)
    return _vector_resolver
```

**Integration:**

```python
# In app/retrieval/engine_v2.py

async def retrieve_async(...):
    # ... existing understand() call
    
    # NEW: Try vector-based matter resolution if standard resolver fails
    if not ctx.matter_ids and parsed.intent in ["argument_search", "matter_research"]:
        resolver = await get_vector_resolver(conn)
        resolved = await resolver.resolve(query, top_k=3, threshold=0.70)
        
        if resolved:
            ctx.matter_ids = [r["matter_id"] for r in resolved]
            latency["matter_resolution"] = "vector"
            latency["matter_resolution_confidence"] = resolved[0]["confidence"]
            logger.info(f"Vector resolver found {len(ctx.matter_ids)} matters")
    
    # ... continue with retrieval
```

**A/B Test Setup:**

```python
# Feature flag
ENABLE_VECTOR_MATTER_RESOLVER = os.getenv("ENABLE_VECTOR_RESOLVER", "false").lower() == "true"

# Evaluation harness
async def eval_with_and_without_vector_resolver():
    results_baseline = await run_eval("evals/independent_search.jsonl", 
                                       filter_type="paraphrase",
                                       enable_vector_resolver=False)
    
    results_vector = await run_eval("evals/independent_search.jsonl",
                                     filter_type="paraphrase", 
                                     enable_vector_resolver=True)
    
    print("Baseline (exact resolver only):")
    print(f"  R@10: {results_baseline['r@10']:.4f}")
    print(f"  Matter resolved: {results_baseline['matter_resolved_rate']:.2f}")
    
    print("\nWith vector resolver:")
    print(f"  R@10: {results_vector['r@10']:.4f}")
    print(f"  Matter resolved: {results_vector['matter_resolved_rate']:.2f}")
    
    print(f"\nLift: {(results_vector['r@10'] - results_baseline['r@10']) * 100:.1f}pp")
```

**Expected Impact:**
- Matter resolved rate: 0% → 60-70%
- Paraphrase R@10: 0.4692 → 0.75-0.80
- Argument channel activation: 0% → 60%+

**Success Criteria:**
- ✅ Matter resolved ≥ 0.60
- ✅ Paraphrase R@10 ≥ 0.75
- ✅ No regression on exact queries

---

### Experiment 2.2: Retrieval-Guided Matter Resolution

**Hypothesis:** Retrieved documents can help identify the matter

**Architecture:**

```
Paraphrase Query
    ↓
Retrieve Top-20 (unscoped)
    ↓
Extract matters from retrieved docs
    ↓
Rank matters by retrieval score
    ↓
Resolve to top matter(s)
```

**Implementation:**

```python
# File: app/retrieval/matter_resolver_v2.py (continued)

class RetrievalGuidedResolver:
    """Resolve matters by looking at what retrieval found."""
    
    async def resolve_from_retrieval(
        self,
        conn,
        query: str,
        member_id: str | None = None,
        top_k_matters: int = 3,
        confidence_threshold: float = 0.5,
    ) -> list[dict]:
        """
        1. Retrieve documents without matter scope
        2. Aggregate scores by matter_id
        3. Return top-K matters above threshold
        """
        
        # Retrieve without scope
        from app.retrieval.engine import retrieve
        hits, _ = retrieve(conn, query, member_id=member_id, k=50)
        
        if not hits:
            return []
        
        # Aggregate by matter
        matter_scores: dict[str, float] = {}
        matter_hit_counts: dict[str, int] = {}
        
        for hit in hits:
            matter_id = hit.get("matter_id")
            if not matter_id:
                continue
            
            score = float(hit.get("score", 0))
            matter_scores[matter_id] = matter_scores.get(matter_id, 0) + score
            matter_hit_counts[matter_id] = matter_hit_counts.get(matter_id, 0) + 1
        
        # Normalize by hit count (average score per matter)
        matter_avg_scores = {
            mid: matter_scores[mid] / matter_hit_counts[mid]
            for mid in matter_scores
        }
        
        # Sort by average score
        ranked = sorted(
            matter_avg_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # Top-K above threshold
        max_score = ranked[0][1] if ranked else 0
        resolved = []
        
        for matter_id, avg_score in ranked[:top_k_matters]:
            # Confidence = normalized score + hit coverage
            confidence = (avg_score / max_score) * 0.7 + (matter_hit_counts[matter_id] / 50) * 0.3
            
            if confidence >= confidence_threshold:
                resolved.append({
                    "matter_id": matter_id,
                    "confidence": confidence,
                    "hit_count": matter_hit_counts[matter_id],
                    "avg_score": avg_score,
                })
        
        logger.info(
            f"Retrieval-guided resolver: {len(resolved)} matters from {len(hits)} hits"
        )
        
        return resolved
```

**Integration (Fallback Chain):**

```python
# In app/retrieval/engine_v2.py

async def retrieve_async(...):
    # ... understand() call
    
    # Matter resolution cascade:
    # 1. Try exact/fuzzy (existing)
    # 2. Try vector-based semantic resolution
    # 3. Try retrieval-guided resolution
    
    if not ctx.matter_ids:
        # Try exact/fuzzy first (fast)
        exact_resolver = get_exact_resolver()
        exact_matters = await exact_resolver.resolve(query, member_id)
        
        if exact_matters:
            ctx.matter_ids = [m["matter_id"] for m in exact_matters]
            latency["matter_resolution"] = "exact"
        
        # Fallback to vector
        elif parsed.intent in ["argument_search", "matter_research"]:
            vector_resolver = await get_vector_resolver(conn)
            vector_matters = await vector_resolver.resolve(query, threshold=0.70)
            
            if vector_matters:
                ctx.matter_ids = [m["matter_id"] for m in vector_matters]
                latency["matter_resolution"] = "vector"
                latency["matter_resolution_confidence"] = vector_matters[0]["confidence"]
            
            # Fallback to retrieval-guided
            else:
                retrieval_resolver = RetrievalGuidedResolver()
                retrieval_matters = await retrieval_resolver.resolve_from_retrieval(
                    conn, query, member_id, confidence_threshold=0.5
                )
                
                if retrieval_matters:
                    ctx.matter_ids = [m["matter_id"] for m in retrieval_matters]
                    latency["matter_resolution"] = "retrieval_guided"
                    latency["matter_resolution_confidence"] = retrieval_matters[0]["confidence"]
    
    # ... continue with retrieval using resolved matters
```

**Expected Impact:**
- Catches paraphrases that vector resolver misses
- Matter resolved rate: 70% → 80%
- Paraphrase R@10: 0.75 → 0.85

**Success Criteria:**
- ✅ Matter resolved ≥ 0.75 (combined with 2.1)
- ✅ Paraphrase R@10 ≥ 0.80
- ✅ Latency penalty ≤ 200ms (retrieval-guided is expensive)

---

## Phase 3: Confidence-Gated Argument Channel (Week 4)

### Experiment 3.1: Confidence-Based Channel Activation

**Problem:** Even with resolution, some matters are uncertain

**Solution:** Gate argument channel by confidence, not binary resolution

**Implementation:**

```python
# In app/retrieval/planner.py

def plan(parsed: ParsedQuery, matter_resolution_confidence: float = 0.0) -> RetrievalPlan:
    """Plan retrieval with confidence-aware channel selection."""
    
    if parsed.intent == "argument_search":
        # High confidence: argument-dominant
        if matter_resolution_confidence >= 0.80:
            return RetrievalPlan(
                channels=["argument", "bm25", "vector", "metadata"],
                weights={
                    "argument": 3.0,
                    "bm25": 0.8,
                    "vector": 0.6,
                    "metadata": 0.4,
                },
                rerank=True,
            )
        
        # Medium confidence: balanced
        elif matter_resolution_confidence >= 0.60:
            return RetrievalPlan(
                channels=["argument", "bm25", "vector", "metadata", "matter"],
                weights={
                    "argument": 1.5,  # Reduced
                    "bm25": 1.0,
                    "vector": 1.0,
                    "metadata": 0.8,
                    "matter": 0.5,
                },
                rerank=True,
            )
        
        # Low confidence: fallback to standard retrieval
        else:
            return RetrievalPlan(
                channels=["bm25", "vector", "metadata", "matter"],
                weights={
                    "bm25": 1.2,
                    "vector": 1.0,
                    "metadata": 0.8,
                    "matter": 0.5,
                },
                rerank=True,
            )
    
    # ... other intents
```

**Metrics:**

```python
# Track argument channel usage by confidence bucket
ARGUMENT_CHANNEL_USAGE = Counter(
    "argument_channel_activations",
    "Argument channel activation by confidence",
    ["confidence_bucket"],
)

# In engine
if "argument" in retrieval_plan.channels:
    confidence_bucket = (
        "high" if matter_confidence >= 0.80 else
        "medium" if matter_confidence >= 0.60 else
        "low"
    )
    ARGUMENT_CHANNEL_USAGE.labels(confidence_bucket=confidence_bucket).inc()
```

**Expected Impact:**
- Argument channel arms more often (60% → 80% of eligible queries)
- Graceful degradation for uncertain resolutions
- Better precision (fewer false activations)

**Success Criteria:**
- ✅ Argument channel activation ≥ 0.75 for paraphrases
- ✅ No false activations (argument channel on non-argument queries)

---

### Experiment 3.2: Multi-Matter Scoping

**Problem:** Some paraphrases could match multiple matters

**Solution:** Scope to top-3 matters instead of top-1

**Implementation:**

```python
# In app/retrieval/engine_v2.py

# Instead of:
ctx.matter_ids = [resolved[0]["matter_id"]]  # Only top-1

# Use:
ctx.matter_ids = [r["matter_id"] for r in resolved[:3] if r["confidence"] >= 0.60]
```

**Trade-offs:**
- ✅ Better recall (catches right matter even if not top-1)
- ❌ Slower (3x scope = 3x partition scan)
- ❌ More noise (false positive matters)

**A/B Test:**

```python
# Test top-1 vs top-3 scoping
results_top1 = await run_eval(enable_multi_matter_scope=False, max_matters=1)
results_top3 = await run_eval(enable_multi_matter_scope=True, max_matters=3)

print(f"Top-1 scoping: R@10 {results_top1['r@10']:.4f}, latency {results_top1['p95_ms']:.0f}ms")
print(f"Top-3 scoping: R@10 {results_top3['r@10']:.4f}, latency {results_top3['p95_ms']:.0f}ms")
```

**Expected Impact:**
- R@10: +3-5pp
- Latency: +100-200ms

**Success Criteria:**
- ✅ Paraphrase R@10 ≥ 0.85
- ✅ P95 latency ≤ 600ms

---

## Phase 4: LLM-Based Matter Disambiguation (Week 5)

### Experiment 4.1: LLM Matter Resolver (Expensive Fallback)

**When:** Only when vector + retrieval-guided both fail

**Implementation:**

```python
# File: app/retrieval/matter_resolver_llm.py

class LLMMatterResolver:
    """Use LLM to extract matter intent from paraphrase."""
    
    async def resolve(
        self,
        conn,
        query: str,
        candidate_matters: list[dict] | None = None,
    ) -> list[dict]:
        """
        Ask LLM to map query to matter(s) from candidate list.
        """
        
        # If no candidates, use top-20 matters from metadata search
        if not candidate_matters:
            candidate_matters = await self._get_candidate_matters(conn, query, limit=20)
        
        # Build LLM prompt
        matter_list = "\n".join([
            f"{i+1}. {m['title']} ({m['matter_code']}) - Client: {m['client_name']}, "
            f"Practice: {m['practice_area']}"
            for i, m in enumerate(candidate_matters)
        ])
        
        prompt = f"""
You are a legal matter resolver. Given a user query and a list of matters,
identify which matter(s) the query refers to.

User Query: "{query}"

Candidate Matters:
{matter_list}

Return a JSON array of matter IDs that match the query, with confidence scores (0-1).
Format: [{{"matter_id": "MTR-XXXX-XXXX", "confidence": 0.95}}]

If no matters match, return an empty array.
"""
        
        # Call LLM
        from app.llm.model_router import get_model_router
        router = get_model_router()
        
        response = await router.complete(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
        )
        
        # Parse response
        try:
            resolved = json.loads(response.content)
            return [r for r in resolved if r.get("confidence", 0) >= 0.70]
        except json.JSONDecodeError:
            logger.error(f"LLM resolver returned invalid JSON: {response.content}")
            return []
    
    async def _get_candidate_matters(self, conn, query: str, limit: int = 20):
        """Get candidate matters via metadata search."""
        from app.retrieval.metadata import metadata_search
        
        hits = metadata_search(conn, query, member_id=None, limit=limit)
        
        # Extract unique matters
        matter_ids = list(set(h.get("matter_id") for h in hits if h.get("matter_id")))
        
        # Fetch matter metadata
        rows = await conn.execute("""
            SELECT matter_id, matter_code, title, client_name, practice_area
            FROM matters
            WHERE matter_id = ANY(%s)
        """, (matter_ids,)).fetchall()
        
        return [dict(row) for row in rows]
```

**Integration (Last Resort):**

```python
# In app/retrieval/engine_v2.py

# After vector and retrieval-guided both fail
if not ctx.matter_ids and parsed.intent == "argument_search":
    llm_resolver = LLMMatterResolver()
    llm_matters = await llm_resolver.resolve(conn, query)
    
    if llm_matters:
        ctx.matter_ids = [m["matter_id"] for m in llm_matters]
        latency["matter_resolution"] = "llm"
        latency["matter_resolution_confidence"] = llm_matters[0]["confidence"]
        latency["llm_resolution_ms"] = latency.get("llm", 0)  # Track LLM cost
```

**Cost Analysis:**

| Resolver | Latency | Cost per Query | Use Case |
|----------|---------|----------------|----------|
| Exact | 5ms | $0 | Direct title/code |
| Vector | 20ms | $0 | Semantic paraphrase |
| Retrieval-guided | 200ms | $0 | Ambiguous queries |
| LLM | 800ms | $0.001 | Last resort |

**Expected Impact:**
- Matter resolved rate: 80% → 90%
- Only used for ~10% of paraphrases (expensive fallback)
- Paraphrase R@10: 0.85 → 0.90

**Success Criteria:**
- ✅ Matter resolved ≥ 0.85
- ✅ LLM usage ≤ 15% of paraphrase queries
- ✅ LLM latency ≤ 1000ms (p95)

---

## Phase 5: Evaluation & Monitoring (Week 6)

### Experiment 5.1: Comprehensive Paraphrase Benchmark

**Expand the holdout:**

```python
# Generate synthetic paraphrases for more coverage
# File: scripts/generate_paraphrase_variants.py

import anthropic
import json

def generate_paraphrase_variants(original_query: str, matter_info: dict, n: int = 5) -> list[str]:
    """Generate n paraphrase variants of a matter query."""
    
    client = anthropic.Client(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    prompt = f"""
Generate {n} paraphrased variations of this legal query:

Original: "{original_query}"

Context:
- Matter: {matter_info['title']}
- Client: {matter_info['client_name']}
- Practice Area: {matter_info['practice_area']}
- Legal Issues: {', '.join(matter_info.get('legal_issues', []))}

Requirements:
1. Each paraphrase should refer to the same matter
2. Vary the phrasing significantly (different sentence structure, word choice)
3. Include indirect references (e.g., "the case involving X" instead of matter title)
4. Make them sound natural, like a lawyer would ask

Return a JSON array of strings.
"""
    
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return json.loads(response.content[0].text)

# Expand holdout from 40 to 200 paraphrases
for matter in get_sample_matters(limit=40):
    original = f"{matter['title']}"
    variants = generate_paraphrase_variants(original, matter, n=5)
    
    for variant in variants:
        write_eval_record({
            "query": variant,
            "gold_matter_id": matter["matter_id"],
            "gold_doc_ids": get_matter_doc_ids(matter["matter_id"]),
            "type": "paraphrase",
        })
```

**Success Criteria:**
- ✅ 200 paraphrase test queries
- ✅ Diverse paraphrase types (direct, indirect, multi-hop, clause-wrapped)

---

### Experiment 5.2: Resolution Confidence Calibration

**Goal:** Ensure confidence scores are well-calibrated

```python
# File: scripts/calibrate_confidence.py

def calibrate_confidence():
    """
    For resolved matters, measure if confidence predicts correctness.
    Well-calibrated: 80% confidence → 80% correct
    """
    
    results = []
    
    for query_record in load_paraphrase_queries():
        query = query_record["query"]
        gold_matter = query_record["gold_matter_id"]
        
        # Resolve with all methods
        resolved = await resolve_matter_all_methods(query)
        
        for method, matters in resolved.items():
            if not matters:
                continue
            
            top_matter = matters[0]
            confidence = top_matter["confidence"]
            correct = (top_matter["matter_id"] == gold_matter)
            
            results.append({
                "method": method,
                "confidence": confidence,
                "correct": correct,
            })
    
    # Bin by confidence and compute accuracy per bin
    bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
    
    for low, high in bins:
        bin_results = [r for r in results if low <= r["confidence"] < high]
        if not bin_results:
            continue
        
        accuracy = sum(r["correct"] for r in bin_results) / len(bin_results)
        avg_confidence = sum(r["confidence"] for r in bin_results) / len(bin_results)
        
        print(f"Confidence [{low:.1f}, {high:.1f}): "
              f"n={len(bin_results)}, "
              f"avg_conf={avg_confidence:.3f}, "
              f"accuracy={accuracy:.3f}")
```

**Expected Output:**

```
Confidence [0.5, 0.6): n=12, avg_conf=0.550, accuracy=0.583  # Decent
Confidence [0.6, 0.7): n=18, avg_conf=0.650, accuracy=0.667  # Good
Confidence [0.7, 0.8): n=24, avg_conf=0.750, accuracy=0.792  # Well-calibrated
Confidence [0.8, 0.9): n=20, avg_conf=0.850, accuracy=0.900  # Excellent
Confidence [0.9, 1.0): n=10, avg_conf=0.950, accuracy=0.950  # Perfect
```

**If poorly calibrated:** Adjust confidence formula or threshold

---

### Experiment 5.3: Production Monitoring

**Metrics to Track:**

```python
# app/observability/metrics.py

MATTER_RESOLUTION_METHOD = Counter(
    "matter_resolution_method_total",
    "Matter resolution attempts by method",
    ["method", "success"],
)

MATTER_RESOLUTION_CONFIDENCE = Histogram(
    "matter_resolution_confidence",
    "Confidence score distribution",
    ["method"],
    buckets=(0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

PARAPHRASE_QUERY_RATE = Gauge(
    "paraphrase_query_rate",
    "Estimated paraphrase query rate (no exact match)",
)

# In resolver
if exact_matters:
    MATTER_RESOLUTION_METHOD.labels(method="exact", success="true").inc()
elif vector_matters:
    MATTER_RESOLUTION_METHOD.labels(method="vector", success="true").inc()
    MATTER_RESOLUTION_CONFIDENCE.labels(method="vector").observe(vector_matters[0]["confidence"])
# ... etc
```

**Grafana Dashboard:**

1. **Matter Resolution Health**
   - Resolution rate by method (stacked area)
   - Confidence distribution (histogram)
   - Fallback cascade depth (how often LLM is needed)

2. **Paraphrase Detection**
   - Estimated paraphrase rate (queries with no exact match)
   - Paraphrase R@10 over time
   - Matter-resolved rate for paraphrases

3. **Latency Breakdown**
   - Matter resolution latency by method
   - Total query latency with/without resolution

---

## Timeline & Success Criteria

| Phase | Experiments | Timeline | Success Criteria |
|-------|-------------|----------|------------------|
| **Phase 1: Diagnostics** | 1.1, 1.2 | Week 1 | Understand current resolver, confirm retrieval quality |
| **Phase 2: Semantic Resolution** | 2.1, 2.2 | Week 2-3 | Matter resolved ≥ 0.75, Paraphrase R@10 ≥ 0.80 |
| **Phase 3: Confidence Gating** | 3.1, 3.2 | Week 4 | Argument channel activation ≥ 0.75, R@10 ≥ 0.85 |
| **Phase 4: LLM Fallback** | 4.1 | Week 5 | Matter resolved ≥ 0.85, Paraphrase R@10 ≥ 0.90 |
| **Phase 5: Evaluation** | 5.1, 5.2, 5.3 | Week 6 | 200-query holdout, calibrated confidence, monitoring |

---

## Rollout Strategy

### Week 1: Diagnostics
1. ✅ Run Experiment 1.1 (resolver autopsy)
2. ✅ Run Experiment 1.2 (retrieval quality check)
3. ✅ Document findings in `docs/paraphrase-resolution-analysis.md`

### Week 2-3: Vector + Retrieval-Guided
1. Implement `VectorMatterResolver` (Exp 2.1)
2. Build matter embeddings index (one-time: ~10 min)
3. A/B test on 20% traffic
4. **Go/No-Go:** If matter resolved ≥ 0.60, proceed to retrieval-guided

5. Implement `RetrievalGuidedResolver` (Exp 2.2)
6. A/B test cascade (exact → vector → retrieval-guided)
7. **Go/No-Go:** If matter resolved ≥ 0.75 && R@10 ≥ 0.80, roll out to 100%

### Week 4: Confidence Gating
1. Implement confidence-based planner (Exp 3.1)
2. A/B test multi-matter scoping (Exp 3.2)
3. Measure argument channel activation rate
4. **Go/No-Go:** If activation ≥ 0.75 && R@10 ≥ 0.85, roll out

### Week 5: LLM Fallback
1. Implement `LLMMatterResolver` (Exp 4.1)
2. Deploy as last-resort fallback (feature flag)
3. Monitor LLM usage rate and cost
4. **Go/No-Go:** If usage ≤ 15% && R@10 ≥ 0.90, keep enabled

### Week 6: Evaluation & Monitoring
1. Generate 200-query paraphrase holdout (Exp 5.1)
2. Run calibration analysis (Exp 5.2)
3. Deploy production monitoring (Exp 5.3)
4. Document final results

---

## Expected Final Metrics

| Metric | Baseline | Target | Method |
|--------|----------|--------|--------|
| **Paraphrase R@10** | 0.4692 | **≥0.85** | Phase 2 + 3 |
| **Paraphrase Hit@10** | 0.6750 | **≥0.90** | Phase 2 + 3 |
| **Matter Resolved (paraphrase)** | 0.00 | **≥0.80** | Phase 2 + 4 |
| **Argument Channel Activation** | 0.00 | **≥0.75** | Phase 3 |
| **Overall R@10** | 0.9121 | **≥0.95** | No regression + paraphrase lift |
| **P95 Latency** | 1726ms | **≤2000ms** | Optimize vector index |

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Vector resolver too slow | Medium | High | Precompute matter embeddings, cache in memory |
| LLM costs too high | Medium | Medium | Strict fallback gating, async batching |
| False positive resolutions | High | Medium | Confidence thresholds, A/B test calibration |
| Regression on exact queries | Low | High | Exact resolver runs first (fast path) |
| Multi-matter scope degrades precision | Medium | Medium | A/B test, tune confidence threshold |

---

## Implementation Checklist

### Phase 2.1: Vector Resolver
- [ ] `app/retrieval/matter_resolver_v2.py` - VectorMatterResolver class
- [ ] `app/embeddings/matter_profiles.py` - Matter profile builder
- [ ] `scripts/build_matter_embeddings.py` - CLI to build index
- [ ] Feature flag: `ENABLE_VECTOR_MATTER_RESOLVER`
- [ ] A/B test harness
- [ ] Metrics: `matter_resolution_method`, `matter_resolution_confidence`

### Phase 2.2: Retrieval-Guided Resolver
- [ ] `app/retrieval/matter_resolver_v2.py` - RetrievalGuidedResolver class
- [ ] Integration with retrieval cascade
- [ ] Latency optimization (async retrieval)
- [ ] A/B test: resolver cascade vs baseline

### Phase 3: Confidence Gating
- [ ] `app/retrieval/planner.py` - Confidence-aware planner
- [ ] Multi-matter scoping logic
- [ ] Argument channel activation metrics
- [ ] A/B test: top-1 vs top-3 scoping

### Phase 4: LLM Fallback
- [ ] `app/retrieval/matter_resolver_llm.py` - LLMMatterResolver class
- [ ] Cost tracking
- [ ] Async batching (if needed)
- [ ] Feature flag: `ENABLE_LLM_MATTER_RESOLVER`

### Phase 5: Monitoring
- [ ] Grafana dashboard: Matter Resolution Health
- [ ] Confidence calibration script
- [ ] 200-query paraphrase holdout
- [ ] Production alerts (low resolution rate, high LLM usage)

---

## Appendix: Example Queries

### Paraphrases That Should Resolve

```json
[
  {
    "query": "What was the case where Acme challenged the bank's termination?",
    "gold_matter": "MTR-2023-0042",
    "expected_resolver": "vector"
  },
  {
    "query": "Find matters involving TechCorp's dispute with the regulator",
    "gold_matter": "MTR-2024-0108",
    "expected_resolver": "vector"
  },
  {
    "query": "Which case dealt with the employment termination of senior executives?",
    "gold_matter": "MTR-2023-0231",
    "expected_resolver": "retrieval_guided"
  },
  {
    "query": "Show me the arbitration where we represented the manufacturer",
    "gold_matter": "MTR-2024-0065",
    "expected_resolver": "vector"
  },
  {
    "query": "What was our argument in the tax dispute for Global Inc?",
    "gold_matter": "MTR-2023-0199",
    "expected_resolver": "retrieval_guided + argument channel"
  }
]
```

---

## Next Steps

1. **Review plan with team** (get sign-off on approach)
2. **Set up experiment tracking** (feature flags, metrics)
3. **Begin Phase 1 diagnostics** (week of 2026-09-16)
4. **Schedule weekly check-ins** (review metrics, make go/no-go decisions)

**Key Decision Point:** After Phase 2 (Week 3), decide whether to proceed with confidence gating or pivot to alternative approach based on vector + retrieval-guided results.
