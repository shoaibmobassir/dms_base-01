# Editor engine bake-off (plan 22, X1)

Re-run (Node 20+ and the backend venv):

    mkdir /tmp/x1 && cd /tmp/x1 && npm init -y && npm i @stll/folio-core@<pinned>   # isolated install
    node bench.mjs in out                     # open, round-trip save, tracked edits (paragraph + table cell)
    node footnote.mjs fn-fixture.docx out/fn-edited.docx   # footnote + header story edits
    python validate.py /tmp/x1                # our checks: text, revisions, comments, authorship, accept/reject, render

`in/` holds the real filings (`docs/*.docx`), generated 10/100/400-page documents (`evals/long_doc/generate.py`) and
held-out files from the object store. Results: `last_validation.json`; decision: `docs/experiments/editor_engine_2026-10.md`.
