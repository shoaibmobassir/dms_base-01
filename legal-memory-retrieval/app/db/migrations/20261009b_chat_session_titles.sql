-- Conversations without a name are named after their first question (the app now does this as the first
-- message is stored), so lists stop showing "Untitled conversation". Names people gave are never changed.
-- Safe to re-run.

UPDATE chat_sessions s
SET title = CASE WHEN length(f.line) <= 70 THEN f.line
                 ELSE rtrim(regexp_replace(left(f.line, 70), '\s+\S*$', ''), ',.;:') || '…' END
FROM (
    SELECT DISTINCT ON (m.session_id) m.session_id, regexp_replace(btrim(m.content), '\s+', ' ', 'g') AS line
    FROM chat_messages m
    WHERE m.role = 'user' AND btrim(m.content) <> ''
    ORDER BY m.session_id, m.created_at
) f
WHERE f.session_id = s.id AND (s.title IS NULL OR btrim(s.title) = '');
