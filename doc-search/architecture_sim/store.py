"""In-memory stores simulating Postgres metadata + object storage + indexes."""
from __future__ import annotations

from dataclasses import dataclass, field

from architecture_sim.models import (
    Annotation,
    Chunk,
    Document,
    DocumentBlock,
    DocumentVersion,
    Finding,
    Folder,
    Matter,
)


@dataclass
class ObjectStore:
    """Simulates S3/MinIO: tenant/matter/document/versions/vN/original.*"""

    blobs: dict[str, bytes] = field(default_factory=dict)

    def put(self, uri: str, data: bytes) -> str:
        self.blobs[uri] = data
        return uri

    def get(self, uri: str) -> bytes:
        return self.blobs[uri]

    def exists(self, uri: str) -> bool:
        return uri in self.blobs


@dataclass
class FirmStore:
    """Canonical firm knowledge graph in memory."""

    matters: dict[str, Matter] = field(default_factory=dict)
    folders: dict[str, Folder] = field(default_factory=dict)
    documents: dict[str, Document] = field(default_factory=dict)
    versions: dict[str, DocumentVersion] = field(default_factory=dict)
    blocks: dict[str, DocumentBlock] = field(default_factory=dict)
    chunks: dict[str, Chunk] = field(default_factory=dict)
    findings: dict[str, Finding] = field(default_factory=dict)
    annotations: dict[str, Annotation] = field(default_factory=dict)
    # version_id -> chunk_ids (never overwrite prior versions)
    version_chunks: dict[str, list[str]] = field(default_factory=dict)
    # document_id -> version_ids ordered
    document_versions: dict[str, list[str]] = field(default_factory=dict)
    objects: ObjectStore = field(default_factory=ObjectStore)

    def versions_for(self, document_id: str) -> list[DocumentVersion]:
        ids = self.document_versions.get(document_id, [])
        return [self.versions[v] for v in ids if v in self.versions]

    def current_version(self, document_id: str) -> DocumentVersion | None:
        doc = self.documents.get(document_id)
        if not doc or not doc.current_version_id:
            return None
        return self.versions.get(doc.current_version_id)

    def chunks_for_version(self, version_id: str) -> list[Chunk]:
        ids = self.version_chunks.get(version_id, [])
        return [self.chunks[c] for c in ids if c in self.chunks]

    def blocks_for_version(self, version_id: str) -> list[DocumentBlock]:
        return sorted(
            [b for b in self.blocks.values() if b.version_id == version_id],
            key=lambda b: b.sequence,
        )

    def docs_in_folder_tree(self, folder_path_prefix: str) -> list[Document]:
        return [
            d
            for d in self.documents.values()
            if d.folder_path.startswith(folder_path_prefix)
        ]
