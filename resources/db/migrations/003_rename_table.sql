ALTER TABLE IF EXISTS jobs RENAME TO upwork_jobs;

ALTER INDEX IF EXISTS idx_jobs_published_date RENAME TO idx_upwork_jobs_published_date;
ALTER INDEX IF EXISTS idx_jobs_scraped_at     RENAME TO idx_upwork_jobs_scraped_at;
ALTER INDEX IF EXISTS idx_jobs_last_seen      RENAME TO idx_upwork_jobs_last_seen;
