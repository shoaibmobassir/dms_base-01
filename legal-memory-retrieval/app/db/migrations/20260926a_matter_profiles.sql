-- One searchable profile per matter: title, parties, client aliases, facts,
-- legal issues, document titles and argument issues folded into one text and
-- one embedding. Used by the Ask-the-Firm matter resolver (app/km/resolver.py)
-- for descriptions that share no words with the title. Rebuilt by
-- scripts/build_matter_profiles.py. ACL is applied at query time. Safe to re-run.
CREATE TABLE IF NOT EXISTS matter_profiles (
    matter_id    TEXT PRIMARY KEY REFERENCES matters (matter_id) ON DELETE CASCADE,
    profile_text TEXT NOT NULL,
    embedding    vector(384),
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', profile_text)) STORED,
    built_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_matter_profiles_tsv ON matter_profiles USING gin (tsv);
