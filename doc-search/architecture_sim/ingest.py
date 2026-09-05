"""Async-style parallel ingestion: preserve folders, immutable versions, structure."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from architecture_sim.cache import VersionedCache
from architecture_sim.corpus import SyntheticFile
from architecture_sim.hashing import embed_text, sha256_text
from architecture_sim.intelligence import enrich_version
from architecture_sim.models import Chunk, Document, DocumentVersion, Folder, Matter
from architecture_sim.observability import Tracer
from architecture_sim.store import FirmStore
from architecture_sim.structure import hierarchical_chunks, parse_structure


@dataclass
class IngestProgress:
    total_files: int = 0
    processed: int = 0
    pages_extracted: int = 0
    chunks_created: int = 0
    embeddings: int = 0
    summaries: int = 0
    errors: list[str] = field(default_factory=list)
    versions_created: int = 0

    def as_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "processed": self.processed,
            "pages_extracted": self.pages_extracted,
            "chunks_created": self.chunks_created,
            "embeddings": self.embeddings,
            "summaries": self.summaries,
            "versions_created": self.versions_created,
            "errors": list(self.errors),
            "pct": round(100.0 * self.processed / self.total_files, 1) if self.total_files else 0.0,
        }


class IngestionManager:
    """
    Upload → Object Store → Structure → Chunks → Embed → Summaries → Index.

    User-facing upload completes after persist + job create; here we simulate
    the worker pipeline synchronously/parallel for the architecture demo.
    """

    def __init__(
        self,
        store: FirmStore,
        cache: VersionedCache | None = None,
        tracer: Tracer | None = None,
        max_workers: int = 8,
    ):
        self.store = store
        self.cache = cache or VersionedCache()
        self.tracer = tracer or Tracer()
        self.max_workers = max_workers
        self.progress = IngestProgress()
        self._matter_by_name: dict[str, str] = {}
        self._folder_by_path: dict[str, str] = {}
        self._lock = threading.Lock()

    def _ensure_matter(self, client: str, matter_name: str) -> str:
        key = f"{client}::{matter_name}"
        with self._lock:
            if key in self._matter_by_name:
                return self._matter_by_name[key]
            mid = f"MAT-{uuid.uuid4().hex[:8].upper()}"
            self.store.matters[mid] = Matter(
                matter_id=mid,
                name=matter_name,
                client_name=client,
                summary=f"Matter {matter_name} for {client}",
            )
            self._matter_by_name[key] = mid
            return mid

    def _ensure_folder(self, path: str) -> str:
        with self._lock:
            if path in self._folder_by_path:
                return self._folder_by_path[path]
            parts = path.strip("/").split("/")
            parent_id: str | None = None
            built = ""
            for part in parts:
                built = f"{built}/{part}" if built else part
                if built in self._folder_by_path:
                    parent_id = self._folder_by_path[built]
                    continue
                fid = f"FLD-{uuid.uuid4().hex[:8].upper()}"
                self.store.folders[fid] = Folder(
                    folder_id=fid,
                    name=part,
                    parent_folder_id=parent_id,
                    path=built,
                )
                self._folder_by_path[built] = fid
                parent_id = fid
            return self._folder_by_path[path]

    def _ingest_one(self, sf: SyntheticFile) -> str:
        try:
            folder_path = "/".join(sf.relative_path.split("/")[:-1])
            matter_id = self._ensure_matter(sf.client_name, sf.matter_name)
            folder_id = self._ensure_folder(folder_path)
            doc_id = f"DOC-{uuid.uuid4().hex[:10].upper()}"

            doc = Document(
                document_id=doc_id,
                matter_id=matter_id,
                folder_id=folder_id,
                name=sf.name,
                document_type=sf.document_type,
                folder_path=folder_path,
            )
            with self._lock:
                self.store.documents[doc_id] = doc
                self.store.document_versions[doc_id] = []

            parent_vid: str | None = None
            local_chunks = 0
            local_embeddings = 0
            local_versions = 0
            local_pages = 0
            local_summaries = 0

            for vnum, body in enumerate(sf.version_bodies, start=1):
                vid = f"VER-{uuid.uuid4().hex[:10].upper()}"
                content_hash = sha256_text(body)
                uri = f"tenant/{matter_id}/{doc_id}/versions/v{vnum:03d}/original.pdf"
                self.store.objects.put(uri, body.encode("utf-8"))

                version = DocumentVersion(
                    version_id=vid,
                    document_id=doc_id,
                    version_number=vnum,
                    parent_version_id=parent_vid,
                    content_hash=content_hash,
                    storage_uri=uri,
                    mime_type="application/pdf",
                    page_count=sf.pages if vnum == len(sf.version_bodies) else max(1, sf.pages),
                    created_by="ingest-worker",
                    change_summary="initial" if vnum == 1 else f"revision v{vnum}",
                    is_current=(vnum == len(sf.version_bodies)),
                    raw_text=body,
                )

                blocks = parse_structure(vid, body)
                chunk_dicts = hierarchical_chunks(
                    document_id=doc_id,
                    matter_id=matter_id,
                    folder_path=folder_path,
                    version_id=vid,
                    blocks=blocks,
                )
                with self._lock:
                    for b in blocks:
                        self.store.blocks[b.block_id] = b
                    enrich_version(version, blocks, self.cache)
                    local_summaries += 1

                    chunk_ids: list[str] = []
                    for cd in chunk_dicts:
                        emb = embed_text(cd["text"])
                        chunk = Chunk(
                            chunk_id=cd["chunk_id"],
                            version_id=vid,
                            document_id=doc_id,
                            matter_id=matter_id,
                            folder_path=folder_path,
                            page=cd["page"],
                            section_id=cd["section_id"],
                            section_title=cd["section_title"],
                            block_ids=cd["block_ids"],
                            text=cd["text"],
                            parent_chunk_id=cd["parent_chunk_id"],
                            position=cd["position"],
                            embedding=emb,
                        )
                        self.store.chunks[chunk.chunk_id] = chunk
                        chunk_ids.append(chunk.chunk_id)
                        local_chunks += 1
                        local_embeddings += 1

                    self.store.version_chunks[vid] = chunk_ids
                    self.store.versions[vid] = version
                    self.store.document_versions[doc_id].append(vid)
                local_versions += 1
                local_pages += version.page_count
                parent_vid = vid

            with self._lock:
                doc.current_version_id = parent_vid
                self.progress.chunks_created += local_chunks
                self.progress.embeddings += local_embeddings
                self.progress.versions_created += local_versions
                self.progress.pages_extracted += local_pages
                self.progress.summaries += local_summaries
                self.progress.processed += 1
            return doc_id
        except Exception as exc:  # noqa: BLE001 — collect per-file errors
            with self._lock:
                self.progress.errors.append(f"{sf.relative_path}: {exc}")
                self.progress.processed += 1
            return ""

    def ingest_batch(self, files: list[SyntheticFile]) -> list[str]:
        self.progress = IngestProgress(total_files=len(files))
        doc_ids: list[str] = []
        with self.tracer.span("ingestion", files=len(files)):
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = [pool.submit(self._ingest_one, sf) for sf in files]
                for fut in as_completed(futures):
                    did = fut.result()
                    if did:
                        doc_ids.append(did)
        # Matter summaries from document summaries
        for matter in self.store.matters.values():
            docs = [d for d in self.store.documents.values() if d.matter_id == matter.matter_id]
            summaries = []
            for d in docs[:20]:
                v = self.store.current_version(d.document_id)
                if v and v.executive_summary:
                    summaries.append(f"{d.name}: {v.executive_summary}")
            matter.summary = " | ".join(summaries)[:2000]
        return doc_ids
