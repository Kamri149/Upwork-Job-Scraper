CREATE TABLE IF NOT EXISTS jobs (
    id              SERIAL PRIMARY KEY,
    cipher          TEXT NOT NULL UNIQUE,
    title           TEXT,
    description     TEXT,
    link            TEXT NOT NULL,
    skills          TEXT[],
    published_date  TIMESTAMPTZ NOT NULL,
    job_type        TEXT NOT NULL,
    is_hourly       BOOLEAN,
    hourly_low      INTEGER,
    hourly_high     INTEGER,
    budget          INTEGER,
    duration_weeks  INTEGER,
    contractor_tier TEXT,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_published_date ON jobs (published_date DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs (scraped_at DESC);
