import logging

from src.models.job_models import Job
from src.postgres.core import get_connection

LOGGER = logging.getLogger(__name__)

DB_FIELDS = [
    "cipher", "title", "description", "link", "skills",
    "published_date", "job_type", "is_hourly",
    "hourly_low", "hourly_high", "budget",
    "duration_weeks", "contractor_tier",
]

_columns = ", ".join(DB_FIELDS)
_placeholders = ", ".join(f"%({f})s" for f in DB_FIELDS)
INSERT_SQL = (
    f"INSERT INTO jobs ({_columns}) VALUES ({_placeholders}) "
    "ON CONFLICT (cipher) DO NOTHING"
)

_DB_FIELDS_SET = set(DB_FIELDS)


def insert_jobs(jobs: list[Job]) -> int:
    if not jobs:
        return 0

    params = [job.model_dump(include=_DB_FIELDS_SET) for job in jobs]

    with get_connection() as conn:
        with conn.pipeline():
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, params)
            conn.commit()

    return len(params)


def has_jobs() -> bool:
    """Fast check for whether the jobs table has any rows."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS(SELECT 1 FROM jobs)")
            return cur.fetchone()[0]


def get_job_count() -> int:
    """Approximate count via pg_class (updated by autovacuum ANALYZE)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = 'jobs'"
            )
            row = cur.fetchone()
            return max(0, row[0]) if row else 0
