-- Collision-free ids for single-document ingest (previously COUNT(*)+1, which
-- reuses ids after deletes and races under concurrent requests).
-- Safe to re-run: setval never moves the sequence backwards.

CREATE SEQUENCE IF NOT EXISTS document_id_seq;

SELECT setval(
    'document_id_seq',
    GREATEST(
        (SELECT last_value FROM document_id_seq),
        (SELECT COALESCE(MAX(substring(document_id FROM 5)::bigint), 0)
           FROM documents WHERE document_id ~ '^DOC-[0-9]+$')
    )
);
