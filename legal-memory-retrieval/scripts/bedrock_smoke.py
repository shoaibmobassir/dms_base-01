#!/usr/bin/env python3
"""Smoke-test Bedrock chat + embedding models for the DMS AI layer.

Usage:
  export AWS_BEARER_TOKEN_BEDROCK=...
  export BEDROCK_REGION=us-east-1   # optional
  python scripts/bedrock_smoke.py

Does not write secrets. Prints PASS/FAIL per model.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.llm.bedrock_client import (  # noqa: E402
    BEDROCK_CHAT_MODELS,
    BEDROCK_EMBED_MODELS,
    bedrock_configured,
    bedrock_region,
    chat_complete,
    embed_texts,
)


def _probe_chat(model: str) -> dict:
    t0 = time.perf_counter()
    try:
        result = chat_complete(
            [
                {
                    "role": "user",
                    "content": "Reply with exactly the JSON object {\"ok\": true}.",
                }
            ],
            model=model,
            temperature=0.0,
            max_tokens=64,
            json_mode=False,
            timeout=60.0,
        )
        ms = round((time.perf_counter() - t0) * 1000, 1)
        content = (result.get("content") or "")[:200]
        return {"ok": True, "ms": ms, "preview": content, "error": None}
    except Exception as exc:  # noqa: BLE001 — smoke report
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": False, "ms": ms, "preview": None, "error": f"{type(exc).__name__}: {exc}"}


def _probe_embed(model: str) -> dict:
    t0 = time.perf_counter()
    try:
        vectors = embed_texts(
            ["Harbour International Chambers institutional memory probe."],
            model=model,
            input_type="search_query",
        )
        ms = round((time.perf_counter() - t0) * 1000, 1)
        dim = len(vectors[0]) if vectors and vectors[0] else 0
        return {"ok": True, "ms": ms, "dim": dim, "error": None}
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": False, "ms": ms, "dim": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    if not bedrock_configured():
        print("FAIL: AWS_BEARER_TOKEN_BEDROCK is not set")
        return 1

    print(f"region={bedrock_region()}")
    print(f"token_prefix={os.environ.get('AWS_BEARER_TOKEN_BEDROCK', '')[:12]}…")
    print("--- chat models ---")
    chat_results = {}
    for model in BEDROCK_CHAT_MODELS:
        row = _probe_chat(model)
        chat_results[model] = row
        status = "PASS" if row["ok"] else "FAIL"
        detail = row["preview"] if row["ok"] else row["error"]
        print(f"[{status}] {model}  {row['ms']}ms  {detail}")

    print("--- embedding models ---")
    embed_results = {}
    for model in BEDROCK_EMBED_MODELS:
        row = _probe_embed(model)
        embed_results[model] = row
        status = "PASS" if row["ok"] else "FAIL"
        detail = f"dim={row['dim']}" if row["ok"] else row["error"]
        print(f"[{status}] {model}  {row['ms']}ms  {detail}")

    out = {"chat": chat_results, "embeddings": embed_results}
    out_path = ROOT / "evals" / "last_bedrock_smoke.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")

    chat_ok = sum(1 for r in chat_results.values() if r["ok"])
    emb_ok = sum(1 for r in embed_results.values() if r["ok"])
    print(f"summary: chat {chat_ok}/{len(chat_results)}  embeddings {emb_ok}/{len(embed_results)}")
    return 0 if (chat_ok + emb_ok) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
