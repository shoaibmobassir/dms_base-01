"""Workbench explorer at scale (plan 22, X4): 10,000 documents in 300 folders of one project, timed over live HTTP.

Rows are inserted directly (no files, no chunks) into a throwaway project and removed afterwards.
    python evals/workbench_load_eval.py --base-url http://127.0.0.1:8021 --member MEM-00001
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from pathlib import Path

import httpx


def main() -> int:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.db.connection import connect
    from app.ingest.purge import purge_projects

    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8021")
    ap.add_argument("--member", default="MEM-00001")
    ap.add_argument("--docs", type=int, default=10_000)
    ap.add_argument("--folders", type=int, default=300)
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base_url, headers={"X-Member-Id": args.member}, timeout=60)
    pid = c.post("/api/projects", json={"title": "E2E-TMP explorer load"}).json()["project_id"]
    folders = [f"Group {i // 30:02d}/Folder {i:03d}" for i in range(args.folders)]
    t = time.perf_counter()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO documents (document_id, title, document_type, body, home_kind, home_id, folder_path)
                   VALUES (%s, %s, 'Load test', '', 'project', %s, %s)""",
                [(f"DOC-LOAD{uuid.uuid4().hex[:8].upper()}", f"Load document {i:05d}.docx", pid, folders[i % args.folders])
                 for i in range(args.docs)])
        conn.commit()
    insert_s = time.perf_counter() - t

    def timed(path, **params):
        times = []
        for _ in range(7):
            t0 = time.perf_counter()
            r = c.get(path, params=params)
            times.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200, r.text[:200]
        return round(statistics.median(times), 1), round(max(times), 1), r.json()

    root_ms, root_max, root = timed(f"/api/workspaces/project/{pid}/items")
    group_ms, group_max, group = timed(f"/api/workspaces/project/{pid}/items", folder="Group 03")
    leaf_ms, leaf_max, leaf = timed(f"/api/workspaces/project/{pid}/items", folder="Group 03/Folder 095")
    search_ms, search_max, _ = timed(f"/api/workspaces/project/{pid}/items", q="Load document 0999", recursive="true")
    quick_ms, quick_max, quick = timed(f"/api/workspaces/project/{pid}/items", recursive="true")
    report = {"documents": args.docs, "folders": args.folders, "insert_s": round(insert_s, 1),
              "root_ms_p50": root_ms, "root_ms_max": root_max, "root_folders": len(root["folders"]),
              "group_ms_p50": group_ms, "group_ms_max": group_max, "group_children": len(group["folders"]),
              "leaf_ms_p50": leaf_ms, "leaf_docs": len(leaf["documents"]),
              "title_filter_ms_p50": search_ms, "quick_open_all_ms_p50": quick_ms, "quick_open_docs": len(quick["documents"]),
              "gate_first_page_lt_300ms": root_ms < 300 and group_ms < 300 and leaf_ms < 300}
    purge_projects([pid])
    Path("evals/last_workbench_load.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
