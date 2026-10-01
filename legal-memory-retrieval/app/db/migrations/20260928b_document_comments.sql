-- Comments on the exact (page) view of a document version (plan 16, E6).
-- Reuses the `annotations` table: a comment is an annotation of type 'comment' with the
-- selected area as boxes in page fractions, optional replies (parent_id) and a resolved state
-- (status 'active' | 'resolved').
-- Safe to re-run.

ALTER TABLE annotations ADD COLUMN IF NOT EXISTS rects JSONB NOT NULL DEFAULT '[]'::jsonb;  -- [{x0,y0,x1,y1}] in 0..1
ALTER TABLE annotations ADD COLUMN IF NOT EXISTS parent_id TEXT REFERENCES annotations (annotation_id) ON DELETE CASCADE;
ALTER TABLE annotations ADD COLUMN IF NOT EXISTS resolved_by_member_id TEXT REFERENCES members (member_id);
ALTER TABLE annotations ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS annotations_document_version_idx ON annotations (document_id, version_id, created_at);
CREATE INDEX IF NOT EXISTS annotations_parent_idx ON annotations (parent_id) WHERE parent_id IS NOT NULL;
