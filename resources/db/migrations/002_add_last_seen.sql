ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;
UPDATE jobs SET last_seen = scraped_at WHERE last_seen IS NULL;
ALTER TABLE jobs ALTER COLUMN last_seen SET NOT NULL;
ALTER TABLE jobs ALTER COLUMN last_seen SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs (last_seen DESC);
