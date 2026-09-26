-- One canonical block per (version, sequence).
-- Block ids were random, so every re-parse (reindex, review, diff, lazy block
-- load) appended another full copy of a version's blocks: the Acme SPA v2 had
-- each block four times, which broke paging in the document viewer.
-- Keep the copy something points at (annotation, evidence anchor), else the
-- lowest id; repoint chunks at the survivor; delete the rest; enforce uniqueness.
-- Safe to re-run.

CREATE TEMP TABLE block_dedupe AS
WITH ranked AS (
    SELECT b.block_id, b.version_id, b.sequence,
           row_number() OVER (
               PARTITION BY b.version_id, b.sequence
               ORDER BY
                   (EXISTS (SELECT 1 FROM annotations a WHERE a.block_id = b.block_id)
                    OR EXISTS (SELECT 1 FROM evidence_anchors e WHERE e.block_id = b.block_id)) DESC,
                   b.block_id
           ) AS rn
    FROM document_blocks b
)
SELECT dup.block_id AS old_id, keep.block_id AS keep_id
FROM ranked dup
JOIN ranked keep ON keep.version_id = dup.version_id AND keep.sequence = dup.sequence AND keep.rn = 1
WHERE dup.rn > 1
  AND NOT EXISTS (SELECT 1 FROM annotations a WHERE a.block_id = dup.block_id)
  AND NOT EXISTS (SELECT 1 FROM evidence_anchors e WHERE e.block_id = dup.block_id);

UPDATE chunks c
SET block_ids = ARRAY(
    SELECT DISTINCT coalesce(m.keep_id, x.block_id)
    FROM unnest(c.block_ids) AS x(block_id)
    LEFT JOIN block_dedupe m ON m.old_id = x.block_id
)
WHERE c.block_ids && ARRAY(SELECT old_id FROM block_dedupe);

DELETE FROM document_blocks d USING block_dedupe m WHERE d.block_id = m.old_id;

DROP TABLE block_dedupe;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM document_blocks GROUP BY version_id, sequence HAVING count(*) > 1
    ) THEN
        CREATE UNIQUE INDEX IF NOT EXISTS uq_document_blocks_version_seq
            ON document_blocks (version_id, sequence);
    ELSE
        RAISE WARNING 'document_blocks still has referenced duplicates; unique index not created';
    END IF;
END $$;
