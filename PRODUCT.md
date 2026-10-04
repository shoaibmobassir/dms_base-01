# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Partners and fee earners at Harbour International Chambers, an international disputes and regulatory practice (PCIJ and Security Council work, Indian electricity regulation and appeals). They work matters: drafting and reviewing Word documents, finding what the firm has argued before, and tracking court dates. Knowledge-management staff and firm administrators use it too, but the day-to-day design centre is the lawyer on a matter.

## Product Purpose

Precentis is the firm's document and knowledge system. It holds the matters, documents, clients, people and court calendar, and it answers questions about the firm's own work. Success is a lawyer finding the right institutional knowledge quickly, trusting where it came from, and never seeing something they are not permitted to see.

## Positioning

Answers come only from records the member is allowed to see, every claim links to the passage it rests on, and ethical walls are applied before anything is retrieved. A general chat assistant or a plain document store cannot truthfully claim that. Two surfaces share one record: Ask the Firm (find what the firm already knows) and the Assistant (draft, review and edit documents, including tracked changes in Word files).

## Operating Context

Matter-centred work in a firm with restricted and walled matters, private drafts, versioned Word documents, court deadlines that a second lawyer must confirm, and conflict checks before new clients. Documents are PDFs and Word files, many long. Sessions are long reading and drafting sessions at a desk, with checks of matters, court dates and documents on a tablet or phone.

## Capabilities and Constraints

- Matters, clients, people, documents (versions, privacy, comments, tracked-change review), calendar and court dates, an argument bank, Ask the Firm, the Assistant, and administration (roles, teams, walls, access requests).
- Access is enforced on the server by matter, document and ethical wall; the interface must never hint at records outside a member's scope.
- Never default a matter, client or privilege on the person's behalf. Filing, attaching and assigning always need an explicit choice.
- Both light and dark themes; full keyboard use and screen-reader support are required.
- Reading, matters and deadlines must work on tablet and phone; heavy drafting is desktop.
- Hindi and other IME input, mixed scripts and long party names must work in every field.
- Terminology: "matter", "Ask the Firm", "Assistant" (the route is `/chat`, but the interface never says "Chat").

## Brand Commitments

Name: Precentis. Firm identity shown in the interface: Harbour International Chambers. The existing wine, ink and paper identity with DM Serif Display page titles is the incumbent and is kept unless the owner changes it.

## Evidence on Hand

A frozen firm corpus in `dummy-firm/` (PCIJ cases, UN Security Council resolutions, Indian electricity filings) loaded into Postgres, a benchmark in `legal-memory-retrieval/evals/`, and Playwright end-to-end coverage of the interface. There are no real client testimonials or usage figures; none should be invented.

## Product Principles

1. Trust is visible: every claim shows its source, and what the system could not support is said plainly.
2. The person decides: confidential choices (matter, client, privilege, deletion) are explicit, never inferred.
3. Work first: dense, scannable, keyboard-friendly screens for people doing matter work; expression stays in precise details.
4. One record, two doors: Ask the Firm and the Assistant hand work to each other without losing the document or the matter.
5. Every state is designed: loading, empty, error, restricted and read-only each say what happened and what to do next.

## Accessibility & Inclusion

Keyboard operable throughout, visible focus, sensible heading and landmark structure, text that respects reduced motion, contrast that holds in both themes, and touch targets that suit tablet and phone. Support Indian and international text input including IME composition.
