# PM Agent — Task Validation & Missing-Link Detection

**Type:** Process document (not a code sprint)  
**Applies to:** Every sprint and every feature doc in `docs/plan/`

---

## Purpose

The PM Agent is a validation layer that runs before any sprint starts and after any sprint completes. Its job is to catch:

- Features described in docs that have no implementation
- Implementation that has no corresponding test
- API endpoints documented but not wired to UI
- UI views that call endpoints that do not exist
- Eval types that exist but score zero and have no sprint planned
- Dependencies added without license audit
- Mike-inspired features without an IP_ORIGIN_RECORD entry

---

## When to run

**Before implementing a sprint:**
1. Read the feature doc for that sprint
2. Run every check in the Pre-Implementation Checklist below
3. Record verdict in the feature doc's `PM Gate` section
4. Only proceed if all P0 blockers are cleared

**After implementing a sprint:**
1. Run every check in the Post-Implementation Checklist below
2. Update `docs/CHANGELOG.md` with actual metrics
3. Update `SKILL.md` Current gate

---

## Pre-Implementation Checklist

### IP & Legal
- [ ] Feature doc exists in `docs/plan/` before first line of code is written
- [ ] If Mike-inspired: IP_ORIGIN_RECORD entry exists for this feature
- [ ] No new AGPL/GPL/SSPL dependency introduced without approval
- [ ] New packages listed in `docs/legal/DEPENDENCY_AUDIT.md`

### Architecture
- [ ] Feature has a clear data model (tables/columns named — our names, not Mike's)
- [ ] API contract defined: route, method, request body, response shape
- [ ] ACL behaviour defined: who can see what
- [ ] Error states defined: what the API returns when input is invalid or access denied
- [ ] No retrieval score regression: `evals/retrieval_eval.py` baseline captured

### UI
- [ ] Every API endpoint the UI calls must exist in the backend
- [ ] Loading and error states designed for every async call
- [ ] No view reads from `firm_core_data.js` for live data — must call API

### Tests
- [ ] At least one unit test planned for new logic
- [ ] At least one integration test planned for new route
- [ ] Eval type covered (if retrieval is involved)

---

## Post-Implementation Checklist

### Code
- [ ] All `TODO` and `FIXME` comments resolved or tracked in CHANGELOG
- [ ] No hardcoded IDs or test-only credentials committed
- [ ] `python evals/retrieval_eval.py` run — result recorded in CHANGELOG
- [ ] No retrieval regression vs previous `last_retrieval_run.json`

### Docs
- [ ] `docs/CHANGELOG.md` updated with actual metrics and file list
- [ ] `SKILL.md` Current gate updated
- [ ] Feature doc `PM Gate` marked PASSED

### UI
- [ ] UI feature tested manually in browser at `http://localhost:8000/ui`
- [ ] No console errors in baseline flows
- [ ] Dark and light themes tested

---

## Missing-Link Detection — Quick Reference

Run these checks at any time:

```bash
# 1. Endpoints defined in FastAPI but not called anywhere in static/app.js
grep -E "^@app\.(get|post)" legal-memory-retrieval/app/api/main.py | sed "s/.*'//" | sed "s/'.*//"
grep -oE '/(retrieve|ask|health|metrics|ui)[^"' ]*' legal-memory-retrieval/static/app.js | sort -u

# 2. Eval types with zero recall
python -c "
import json
data = json.load(open('legal-memory-retrieval/evals/last_retrieval_run.json'))
for t, r in data['by_type'].items():
    if r['recall@10'] == 0.0:
        print(f'ZERO recall: {t} (n={r[\"n\"]})')
"

# 3. Tables in schema with no retrieval channel
# arguments table: is it used?
grep -r "arguments" legal-memory-retrieval/app/retrieval/ --include="*.py" | wc -l

# 4. IP_ORIGIN_RECORD completeness vs plan docs
grep "^### Feature:" legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md | sort
ls legal-memory-retrieval/docs/plan/
```

---

## PM Gate Template

Add this block to every feature doc before implementation:

```markdown
## PM Gate

**Status:** PENDING / PASSED / BLOCKED

**Pre-implementation checks:**
- [ ] Feature doc written
- [ ] IP_ORIGIN_RECORD entry (if Mike-inspired)
- [ ] Data model defined
- [ ] API contract defined
- [ ] No new unlicensed dependency
- [ ] Test plan written

**Post-implementation checks:**
- [ ] Retrieval eval: no regression (before: X, after: X)
- [ ] Manual UI test passed
- [ ] CHANGELOG updated
- [ ] SKILL.md gate updated
```

---

## Escalation rule

If any check is UNCERTAIN (not clearly yes or no), treat it as BLOCKED and do not proceed with implementation. Record the uncertainty in the feature doc and resolve it before the next session.
