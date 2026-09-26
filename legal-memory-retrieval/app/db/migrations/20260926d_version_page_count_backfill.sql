-- Versions created through create_version() never recorded page_count, so the
-- viewer fell back to five-block "parts". Backfill from blocks that span more
-- than one page (app.documents.sync_page_count keeps it current). Safe to re-run.
UPDATE document_versions v
SET page_count = b.pages
FROM (SELECT version_id, max(page_number) AS pages FROM document_blocks GROUP BY version_id) b
WHERE b.version_id = v.version_id AND v.page_count IS NULL AND b.pages > 1;
