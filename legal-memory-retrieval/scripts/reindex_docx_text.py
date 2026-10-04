"""Re-read Word documents indexed with the old "SECTION " heading label (see app/documents/docx_reindex.py).

    python scripts/reindex_docx_text.py                 # dry run: what would change, per version
    python scripts/reindex_docx_text.py --apply         # write it
    python scripts/reindex_docx_text.py --doc DOC-7405413EC8 --apply

Stored Word files are only read. Version text, blocks, the current version's chunks and their embeddings are rebuilt.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import connect  # noqa: E402
from app.documents.docx_reindex import affected_documents, apply, plan  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--doc", action="append", help="limit to these document ids")
    ap.add_argument("--backup", default=f"data/backups/reindex_docx_{datetime.now():%Y%m%d_%H%M%S}.json")
    a = ap.parse_args()
    with connect() as conn:
        docs = affected_documents(conn, a.doc)
        print(f"{len(docs)} Word document(s) with the old heading label")
        if a.apply and docs:
            # The text being replaced, so the change can be undone (blocks and chunks are rebuilt from it).
            ids = [d["document_id"] for d in docs]
            backup = {
                "versions": [dict(r) for r in conn.execute(
                    "SELECT version_id, document_id, body, content_sha256 FROM document_versions WHERE document_id = ANY(%s)", (ids,))],
                "documents": [dict(r) for r in conn.execute(
                    "SELECT document_id, body FROM documents WHERE document_id = ANY(%s)", (ids,))],
            }
            path = Path(a.backup)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(backup, default=str))
            print(f"backup of the current text: {path}")
        for doc in docs:
            p = plan(conn, doc)
            print(f"\n{doc['document_id']}  {doc['title']}: {len(p.versions)} version(s) to re-read")
            for v in p.versions:
                if "error" in v:
                    print(f"  v{v['version_number']}: file not readable ({v['error'][:80]}), left as it is")
                    continue
                changed = [line for line in difflib.unified_diff(v["before"].split("\n"), v["after"].split("\n"), lineterm="", n=0)
                           if line[:1] in "+-" and not line.startswith(("+++", "---"))]
                print(f"  v{v['version_number']}: {len(changed) // 2} line(s), e.g. " + " | ".join(changed[:2]))
            if a.apply and p.versions:
                print("  applied:", apply(conn, p))
        if not a.apply:
            print("\nDry run: nothing written. Add --apply to write.")


if __name__ == "__main__":
    main()
