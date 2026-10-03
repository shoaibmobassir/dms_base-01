# Ask the Firm: docket pin, then store the answer

**Status:** implemented. Validated with `tests/test_ask_docket_and_saved.py` and the Ask suite.  
**Question that exposed it:** `APPEAL NO. 163 OF 2018 , have we prepared brief note of arguments in this appeal ?`  
**Page:** `/ui/ask?q=…`

---

## What the page did

The question names a proceeding and a document type. It does not name a client.

The answer led with Maharashtra State Electricity Distribution Company Limited (MSEDCL), Respondent No. 2, and then listed four documents across two matters:

| Document the panel showed | Matter |
|---|---|
| Brief note of submissions on behalf of MSEDCL in Appeal 163 of 2018 | `REG/DEL/0166/2018` |
| MSEDCL note in Appeal 163 of 2018 | `REG/DEL/0166/2018` |
| BRIEF NOTE OF SUBMISSIONS ON BEHALF OF RESPONDENT NO. 2, MSEDCL.pdf | `CI-OPEN-001` |
| MSEDCL Note in APL. 163 of 2018.pdf | `CI-OPEN-001` |

`CI-OPEN-001` is CI Energy Utility Ltd, a different client. The same PDFs were uploaded there on 2026-09-24. The other three matters on the page (`REG/DEL/0165/2025`, `0167/2026`, `0168/2025`) are `similar_facts` neighbours of `REG/DEL/0166/2018`. They are not Appeal 163 of 2018.

Refreshing or reopening the question runs the whole pipeline again. The Assistant does not do that.

---

## Why MSEDCL appeared

Nothing in query parsing inserts a client. `app/query/understand.py` does not extract appeal numbers, and `app/km/resolver.py` scores matters as bags of stems (title, client, facts, document titles). “Appeal”, “163”, “2018”, “brief”, “note” hit every matter whose **document titles** contain those words.

That is two matters here:

1. `REG/DEL/0166/2018` — title is “GMR Warora Energy v CERC — Appeal 163 of 2018”. Client on the matter record is MSEDCL. The brief note in the corpus is written for MSEDCL as Respondent No. 2.
2. `CI-OPEN-001` — holds uploaded copies of those same MSEDCL PDFs, so its document-title stems score too.

The resolver only locks a matter when one score clears `RESOLVE_MIN` (0.55) and beats the runner-up by `RESOLVE_MARGIN` (0.12). Two matters sharing the same filing titles stay tied, so `gather_evidence` in `app/km/answer.py` falls through to unscoped `retrieve()`. Hard matter scope then keeps both matter ids in the universe. The model is told to answer from that evidence, and the evidence’s titles and the matter card both say MSEDCL. The client in the answer is copied from the sources. It was not asked.

A correct reply to this question is still allowed to name MSEDCL, because that is who the note in `REG/DEL/0166/2018` is for. It must say that as a fact from the record, after pinning the proceeding, and it must not treat the `CI-OPEN-001` copies as a second appeal.

Secondary defects in the same reply, same root:

- The key finding and the first paragraph both say “yes”, because the model repeated itself and grounding kept both.
- “Brief note of arguments” was answered with “Brief note of submissions” with no line that the record uses that title.
- The line `REG/DEL/0166/2018 MEM-00015MEM-00016MEM-00011` is citation chips rendered with no copied separator. Matter chips show the matter code; member chips show the raw id when the name is not on the card passed to the page (`AIAnswer.tsx` `withCitationChips`).

---

## Why every open calls the API

Ask and the Assistant persist different things.

| | Ask the Firm | Assistant |
|---|---|---|
| Identity | URL `?q=` and optional `scope` | `/chat/:sessionId` |
| What is stored | `ask_history`: question text, scope label, time (`app/km/ask_history.py`) | `chat_messages`: content, citations, events, model (`app/chat/store.py`) |
| On open | `useAskStream` always `POST /api/answers/stream` (`frontend/src/api/ask.ts`) | `getSession` reads the stored thread (`ChatPage.tsx`) |
| Model | Runs on every visit, including history clicks and reload | Runs only when a new message is sent |

`ask_history.record` is called at the start of `POST /api/answers` and `POST /api/answers/stream`, before evidence is gathered. The comment in `ask_history.py` says the answer is recomputed on purpose so the matter ACL at read time still applies. That reason is real. Recomputing the model, retrieval, and grounding on every navigation is not required to honour it.

Cost of the current design: a reload spends a full Bedrock call plus grounding (`_ground` reads up to 25 full documents), the wording can change between visits, and “recent questions” is a list of strings that each mean “ask again”.

---

## Plan

### 1. Pin a proceeding number before retrieval

Add a docket parse in front of the stem resolver. Independent of any other product. Pattern covers the forms already in this corpus: `Appeal No. 163 of 2018`, `APL. 163 of 2018`, `Appeal 163 of 2018`, `Civil Appeal 10046 of 2025`, `Petition 310/MP/2026`.

Match the number against matter title and document title, case-insensitively, as a phrase, not as stems `163` and `2018` separately.

- One accessible matter contains that phrase in its **title** → scope Ask to that matter only (`kind=matter`, method `docket`). Document-title hits on other matters do not widen the scope.
- The phrase is only in document titles, on more than one matter → do not merge them. Answer from the matter whose title contains the number. List the other matters as “copies of this filing also sit on …” and do not cite them as the appeal.
- No title match → keep today’s resolver.

`understand()` should record `docket` on `ParsedQuery` so retrieval evals can see it. Do not change fusion weights.

### 2. Answer the document question inside that matter

Once scoped, search passages for the document type the user named (`brief note`, `note of arguments`, `written submission`). 

- A matching filing exists → first sentence is yes or no, then the document title as stored, the forum, and the client **as printed on that matter record**. One matter card.
- The stored title differs from the words in the question (`submissions` vs `arguments`) → one sentence saying the record uses the stored title.
- No filing of that type on the pinned matter → `insufficient` or a clear no, citing the matter record. Do not fill the gap from a similarly named upload on another matter.

Stop the key finding from repeating the body’s first sentence. If they are the same claim, show it once.

### 3. Store the answer the way the Assistant stores a turn

New table `ask_answers`, one row per member + question + scope (same uniqueness as `ask_history`):

- `id`, `member_id`, `query`, `scope`, `scope_type`, `asked_at`
- `answer`, `key_finding`, `status`, `provider`, `model`
- `citations` jsonb, `span_citations` jsonb, `panel` jsonb, `matter_cards` jsonb, `sources` jsonb
- `corpus_version` or `answered_at` so a stale row can be detected after ingest

Write the row at the end of `_publish` in `app/api/routers/answers.py`, after grounding. Keep `ask_history` as the sidebar index, or fold it into this table and stop writing the question-only row.

Read path:

- `GET /api/answers/saved?q=&scope=` returns the stored payload when the member still passes ACL on every matter id inside `panel` and `sources`. If any cited matter is no longer visible, drop the row and return 404.
- The Ask page loads that GET when `?q=` is present. It calls `POST /api/answers/stream` only when there is no stored row, the user clicks Refresh, or `runKey` changes.
- Recent-question clicks navigate to `?q=` and render the stored answer. They do not stream.

ACL stays at read time. The model does not.

### 4. Tests

- “Appeal No. 163 of 2018” + “brief note” scopes to `REG/DEL/0166/2018` only, even when `CI-OPEN-001` holds the same PDF titles.
- The answer may name MSEDCL because the matter client and the note’s title do. It may not cite `CI-OPEN-001` as the appeal.
- A question that names no proceeding still uses the stem resolver.
- Second `POST /api/answers/stream` with the same member, query, and scope does not call the model when a stored row exists and the caller did not pass `refresh=true`.
- A member who loses access to the matter gets no stored answer back.
- Opening `/ui/ask?q=…` for a saved question issues the GET and does not POST the stream (Playwright, one case).

---

## Out of scope

- Retuning fusion or turning on evidence cross-encoder flags.
- Changing how the Assistant stores threads.
- Deduplicating the uploaded PDFs on `CI-OPEN-001` in the corpus. The pin above stops them from answering this question; a separate ingest cleanup can remove the copies.
