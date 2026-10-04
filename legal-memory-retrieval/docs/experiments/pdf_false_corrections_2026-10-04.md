# The Assistant "corrected" a PDF that was fine (2026-10-04)

Report: asked to "suggest edits that improve this document" on `Rejoinder to reply of IA.pdf`, the Assistant said it
corrected *knowledgeand → knowledge and* in the Verification. The printed page is correct, "and there are many more
like this".

## What was wrong (measured, not assumed)

- The PDF has 16 pages: pages 1–13 are born-digital (exported from Word: real fonts, no images); pages 14–16,
  including the Verification, are **scanned images with an embedded OCR text layer**.
- The glued word is in that text layer itself. `pdfplumber` extracts `knowledgeand` exactly as `pypdf` does, and the
  character boxes show no space glyph between the `e` and the `a`. So a different extraction library cannot fix it;
  the first idea in the plan ("swap the extractor") was dropped after this measurement.
- Our database holds `knowledgeand` once and `knowledge and` zero times.
- `propose_edits` only checked that the quoted passage exists in our extracted text (`locate_quote`). An artifact
  always exists there, so it was always shown. The system prompt and tool description said nothing about it.
- The same text also hurt search: "knowledge and belief" cannot match a page that reads `knowledgeand`.

## What was built

| Layer | Change |
|---|---|
| Page provenance | `app/documents/text_origin.py`: a page is `scanned_ocr` when it carries a page-sized image (≥ 100 dpi across ≥ 80% of both dimensions), else `born_digital`. Read from the stored PDF and cached by file hash; no migration, no backfill. Real uploads: Rejoinder pages 14–16, the others between 0 and 11 scanned pages |
| What the model reads | `read_document` returns `source` (PDF, read-only, scanned pages) and **marks each scanned page inside the text**: `[Page 16 - SCANNED PAGE: machine-read text, so spacing and letters may be misread; do not report them as errors]`. Stored text and citations are unchanged |
| Prompt | PDF is read-only: recommendations only; never suggest or describe spacing, hyphenation or single-letter differences in PDF text as errors |
| Edit cards | `app/chat/tools/edit_guard.py`, applied in `propose_edits` and `edit_document`: (1) on any PDF, an edit that differs only in spacing, hyphenation, line breaks or ligatures is dropped; (2) on a scanned page, a one-word change to a look-alike word is dropped when the odd word occurs at most once in the document and the corrected word at least twice. A number in the changed words, an insertion, a deletion, or a change between two common words is always kept (*lessee* → *lessor*, `1,20,00,000` → `1,50,00,000`). Word files are untouched |
| Answer prose | the same test applied to the final answer: a line that quotes a word found only on a scanned page and calls it a spacing/OCR/spelling error is removed, as is a list item whose quoted original and quoted fix differ only as a scan's reading would |
| Read-only | cards for a PDF render as "Recommendations · PDF is read-only" with no Accept/Reject/Word-file controls; `POST …/edits/export` returns 409 for a PDF |

Considered and not built: word-geometry confirmation of spacing (a fresh Tesseract read per proposal) and a
license-clean extractor swap (`pdfplumber`). Neither is needed once spacing edits on PDFs are dropped outright.
PyMuPDF is AGPL and is not used.

## Results

Rule-level (`evals/pdf_artifact_eval.py`, 408 artifacts mined from or injected into the scanned pages of the 7 real
uploaded PDFs; 7 real, 401 injected; injected ones follow the rules by construction, so they test coverage not realism):

| | before | after |
|---|---|---|
| False-correction rate (artifact "fixes" shown) | 100% (all are found in the text) | **0%** |
| Number changes kept (n = 277) | 100% | 100% |
| Real word swaps between common words kept (n = 11) | 100% | 100% |
| Typo fixes against a Word source kept (n = 7) | 100% | 100% |
| Look-alike typo fixes on born-digital PDF pages kept (n = 8) | 100% | 100% |

Live, through the running API on the real PDF with your exact request (`evals/pdf_edit_live.py`; generator `zai.glm-5`).
The original behaviour is the one you reported (a "knowledgeand" correction card). The middle column is the first fix
alone (card filter and prompt, 3 runs); the last is everything above (10 runs):

| | as reported | cards + prompt only (3 runs) | all layers (10 runs) |
|---|---|---|---|
| Edit cards that only fix spacing | shown | 0 | **0** |
| Answers that report `knowledgeand` / `thcrein` as errors in prose | shown | 2 of 3 | **0 of 10** |
| Answers that find a real defect on the born-digital pages | n/a | n/a | 8 of 10 |
| Cards marked read-only | no | n/a | 27 of 27 |

The real defects the Assistant should find, and does: the tribunal name is misspelled "ELECTRCITY" on pages 1–2 (page
15 spells it right), and "the Electricity, 2003" on page 3 lacks "Act". Both are on born-digital pages, so the text is
what the author typed.

## Limits

- 10 live runs per condition, one model, one document. The 0 of 10 has a wide interval; 8 of 10 real-defect
  recall shows the filter is not suppressing legitimate findings but is not a recall benchmark.
- The prose check is lexical: it removes lines that quote a scan-only word and call it an error, and items whose
  quoted pair differ only as a scan would. A paraphrase that quotes nothing passes. The answer may still say the
  verification page "has OCR errors", which is at least accurate about the cause.
- A real one-letter slip on a **scanned** page whose odd word is rare and whose correct form is common ("tbe") is
  dropped; the lawyer cannot tell it from OCR noise without the image. It is listed under the drop count the model
  sees, and the reading can be checked on the scan.
- *Lessee*/*lessor* swaps survive only while both words are common in the document; if the odd word occurs once and
  the other twice or more it would be dropped. Rare in practice, but it is a drop, not a flag.
- The model sometimes quotes text that is not in the document (one run reported a `Hon\'ble` "formatting error"
  with a backslash that the stored text does not contain). Grounding does not catch that class; it is not changed here.
- When grounding removes unsupported statements, numbered headings can be left empty (`**4.` with nothing under it).
  That is the existing behaviour, only partly mitigated by the prose check.
- The text-origin detector uses image size, so a born-digital page that is one full-page picture is treated as scanned
  (conservative: it only suppresses typo-level edits).

## Next

1. Persist `text_origin` with the document so search and ingest can use it, and normalize known OCR glue
   ("knowledgeand") for search only, without changing the stored text.
2. Hallucinated quotes (the backslash case) need a check against the stored text before an answer line is kept.
