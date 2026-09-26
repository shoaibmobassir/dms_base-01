-- BM25 match vector stored per chunk: chunk text plus the document title and
-- matter code at weight A. The search channel used to build this concatenation
-- per row at query time, which forced a sequential scan of every chunk
-- (~0.9 s for common words, p95 25 s under 20 concurrent requests).
-- Same vector as before, so ranking is unchanged; now it is GIN-indexed.
-- Maintained by triggers for every writer of chunks and document titles. Safe to re-run.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv_full tsvector;

CREATE OR REPLACE FUNCTION chunks_tsv_full_compute(p_tsv tsvector, p_text text, p_document_id text)
RETURNS tsvector LANGUAGE sql STABLE AS $$
    SELECT coalesce(p_tsv, to_tsvector('english', coalesce(p_text, '')))
        || setweight(to_tsvector('english', coalesce(d.title, '')), 'A')
        || setweight(to_tsvector('english', coalesce(d.matter_code, '')), 'A')
    FROM documents d WHERE d.document_id = p_document_id
$$;

CREATE OR REPLACE FUNCTION chunks_tsv_full_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv_full := coalesce(
        chunks_tsv_full_compute(NEW.tsv, NEW.text, NEW.document_id),
        coalesce(NEW.tsv, to_tsvector('english', coalesce(NEW.text, '')))
    );
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_chunks_tsv_full ON chunks;
CREATE TRIGGER trg_chunks_tsv_full
    BEFORE INSERT OR UPDATE OF tsv, text, document_id ON chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_tsv_full_trigger();

CREATE OR REPLACE FUNCTION documents_tsv_full_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.title IS DISTINCT FROM OLD.title OR NEW.matter_code IS DISTINCT FROM OLD.matter_code THEN
        UPDATE chunks SET tsv_full = chunks_tsv_full_compute(tsv, text, document_id)
        WHERE document_id = NEW.document_id;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_documents_tsv_full ON documents;
CREATE TRIGGER trg_documents_tsv_full
    AFTER UPDATE OF title, matter_code ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_tsv_full_trigger();

UPDATE chunks c
SET tsv_full = coalesce(c.tsv, to_tsvector('english', coalesce(c.text, '')))
    || setweight(to_tsvector('english', coalesce(d.title, '')), 'A')
    || setweight(to_tsvector('english', coalesce(d.matter_code, '')), 'A')
FROM documents d
WHERE d.document_id = c.document_id AND c.tsv_full IS NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_tsv_full ON chunks USING gin (tsv_full);
ANALYZE chunks;
