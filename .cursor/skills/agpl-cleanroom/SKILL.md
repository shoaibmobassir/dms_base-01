---
name: agpl-cleanroom
description: >-
  AGPL clean-room development protocol. Use when working on any feature that
  draws inspiration from Mike (AGPLv3). Converts Mike product observations into
  clean, independent requirements and blocks source-code derivation.
---

# AGPL Clean-Room Development Skill

## When this skill applies

Invoke this skill whenever a task references Mike, the Mike repository, or a
feature that was first observed in Mike. It overrides normal implementation
shortcuts and forces a requirements-first, independent-design workflow.

---

## Activation checklist

Before writing any code, answer these five questions:

1. **What user problem does this feature solve?**
2. **Who is the user and what is their desired outcome?**
3. **What are the functional requirements in plain English?**
4. **What are the security / permission requirements?**
5. **How will we measure success?**

Only after answering all five may implementation begin.

---

## The clean-room pipeline

```
OBSERVE (Mike product)
    │
    │  Extract only: problem, user, outcome, general workflow
    │
    ▼
ABSTRACT (technology-independent requirement)
    │
    │  Forget: Mike's table names, function names, file structure
    │
    ▼
DESIGN (our own architecture)
    │
    │  Choose: our schema, our API shape, our component names
    │
    ▼
IMPLEMENT (from requirements, not from Mike source)
    │
    │  Write: original code traceable to our requirement docs
    │
    ▼
AUDIT (pre-commit IP check)
    │
    │  Confirm: no Mike source copied or transformed
    │
    ▼
COMMIT
```

---

## Requirement template

Use this template to document every Mike-inspired feature before implementation:

```
Feature:          [name]
Date:             [YYYY-MM-DD]
Inspiration:      Mike product observation — [what you saw at the product level]
Requirement:      [technology-independent user story]
Our design:       [our schema / API / component decisions — independently chosen]
Mike NOT used as: source code basis
Dependencies:     [list any new packages + their licenses]
IP notes:         [any uncertainty → escalate before implementing]
```

Save to: `legal-memory-retrieval/docs/legal/IP_ORIGIN_RECORD.md`

---

## Transformation test (run before committing)

For each file in this change, can you answer YES to all of the following?

- The code was written from our requirements document, not from Mike source
- No Mike function body, class, or module was reproduced
- No Mike SQL was copied or adapted
- No Mike test was copied
- No Mike prose, comment, or documentation was copied
- No Mike UI component or asset was copied
- Every new dependency has a recorded license

If any answer is NO or UNCERTAIN → stop, do not commit, escalate.

---

## Dependency audit protocol

Before `pip install` / `npm install` of any new package:

1. Check license on PyPI / npm
2. Record in `docs/legal/DEPENDENCY_AUDIT.md`:

```
| Package | Version | License | Copyleft? | Network-use obligations? | Approved |
```

Licenses requiring human approval before use:
- AGPL, GPL, LGPL (any version)
- SSPL, Elastic License v2, BSL, Commons Clause
- Any license with source-disclosure triggers
- Any custom or proprietary license

---

## "Better than Mike" principle

For every feature inspired by Mike, ask:
> What would a better solution to this user problem look like — unconstrained by how Mike did it?

Then implement that. The goal is a superior independent product, not a cleaner copy.

---

## Escalation contacts

Any IP uncertainty → stop work and flag to project owner before continuing.
For commercial launch → obtain qualified legal counsel review.
