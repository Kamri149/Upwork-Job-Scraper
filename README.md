# Upwork Job Scraper

Long-running Docker service that continuously fetches public Upwork job listings via their GraphQL API and stores them in PostgreSQL. Uses `curl_cffi` with Chrome TLS fingerprint impersonation to bypass Cloudflare — no browser, no Selenium, no Lambda, no Kafka.

## Architecture

```
src/
├── auth/token_manager.py              # Fetch + cache visitor_gql_token (25 min TTL, 3 retries with proxy rotation)
├── controllers/scraper_controller.py  # Main loop, signal handling, retry/backoff
├── errors/base_errors.py              # TokenExpired, TokenFetchFailed
├── log/log_config.py                  # init_logger() with MaxLevelFilter
├── models/
│   ├── job_models.py                  # Pydantic models for GraphQL response
│   └── proxy_models.py                # ProxyConfig with to_curl_cffi_dict()
├── postgres/
│   ├── core.py                        # ConnectionPool (psycopg3), get_connection()
│   └── jobs.py                        # insert_jobs(), get_job_count(), has_jobs()
├── proxies/proxy_manager.py           # WebshareProxyManager — loads, rotates, auto-refreshes hourly
├── scrapers/job_fetcher.py            # GraphQL query, concurrent pagination (10 workers)
└── settings/config.py                 # All env vars
```

## How It Works

1. On startup, the proxy list is downloaded from Webshare and the Postgres connection pool is opened
2. If the database is empty, a **bulk scrape** runs first — fetching up to 1000 pages (Upwork's API caps pagination at offset ~5000, so ~100 pages is the practical limit)
3. For every subsequent cycle, `MAX_PAGES` pages are fetched (default: 3 pages × 50 jobs = 150 jobs)
4. Pages are fetched concurrently using a `ThreadPoolExecutor` with 10 workers, each using a randomly selected proxy
5. The token fetch also rotates proxies on each retry — if one proxy IP is blocked by Cloudflare, the next attempt uses a different one
6. Jobs are inserted into PostgreSQL with `ON CONFLICT (cipher) DO NOTHING` for deduplication
7. The scraper sleeps `SCRAPE_INTERVAL` seconds then repeats

## Token Lifecycle

- `curl_cffi` hits `https://www.upwork.com/` with `impersonate="chrome"` through a Webshare proxy
- Upwork sets a `visitor_gql_token` cookie which is used as a Bearer token for all GraphQL API calls
- The token is cached for 25 minutes and reused across cycles
- On 401 responses the token is invalidated and re-fetched immediately
- After 3 consecutive token expiry failures the scraper backs off for 5 minutes

## Environment Variables

| Variable            | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `DATABASE_URL`      | Yes      | —       | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Yes      | —       | PostgreSQL password (used by Docker Compose) |
| `WEBSHARE_URL`      | Yes      | —       | Webshare proxy list download URL |
| `SCRAPE_INTERVAL`   | No       | 120     | Seconds to sleep between scrape cycles |
| `MAX_PAGES`         | No       | 3       | Pages to fetch per cycle (50 jobs/page) |

## Setup

This scraper does not manage its own database. It connects to the shared PostgreSQL instance defined in [`../infra`](../infra).

### 1. Start the shared database

```bash
cd ../infra
docker compose up -d db
```

### 2. Run the migrations

```bash
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper < resources/db/migrations/001_create_jobs_table.sql
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper < resources/db/migrations/002_add_last_seen.sql
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper < resources/db/migrations/003_rename_table.sql
```

### 3. Get a Webshare proxy URL

Create an account at [webshare.io](https://webshare.io) and copy your proxy list download URL from the dashboard. It looks like:

```
https://proxy.webshare.io/api/v2/proxy/list/download/YOUR-TOKEN/
```

The free tier (10 proxies) is enough to get started. If you see repeated 403 errors, the proxy IPs may be flagged by Cloudflare — upgrading to a paid plan with more IPs reduces this risk.

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
POSTGRES_PASSWORD=your_password
DATABASE_URL=postgresql://job_scraper:your_password@localhost:5432/job_scraper
WEBSHARE_URL=https://proxy.webshare.io/api/v2/proxy/list/download/YOUR-TOKEN/
```

### 5. Start the scraper

```bash
docker compose up -d --build
```

## Common Commands

### Logs

```bash
# Stream live logs
docker compose logs -f scraper

# Last 100 lines
docker compose logs --tail=100 scraper
```

### Status

```bash
# Check running containers
docker ps

# Check scraper status
docker compose ps
```

### Database

```bash
# Connect to the database interactively
docker exec -it job-scraper-db psql -U job_scraper -d job_scraper

# Count all scraped jobs
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper -c "SELECT COUNT(*) FROM upwork_jobs;"

# Jobs by type
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper -c "SELECT job_type, COUNT(*) FROM upwork_jobs GROUP BY job_type ORDER BY count DESC;"

# Jobs by contractor tier
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper -c "SELECT contractor_tier, COUNT(*) FROM upwork_jobs GROUP BY contractor_tier ORDER BY count DESC;"

# Most recently scraped jobs
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper -c "SELECT title, job_type, published_date FROM upwork_jobs ORDER BY scraped_at DESC LIMIT 20;"

# Jobs scraped in the last 24 hours
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper -c "SELECT COUNT(*) FROM upwork_jobs WHERE scraped_at >= NOW() - INTERVAL '24 hours';"

# Export all jobs to CSV
docker exec -i job-scraper-db psql -U job_scraper -d job_scraper -c "\COPY (SELECT * FROM upwork_jobs) TO STDOUT WITH CSV HEADER" > upwork_jobs.csv
```

### Control

```bash
# Stop the scraper
docker compose down

# Restart the scraper (e.g. after changing .env)
docker compose up -d

# Rebuild the scraper image (e.g. after a code change) then restart
docker compose up -d --build scraper
```

## Database

Jobs are stored in the `upwork_jobs` table inside the shared `job_scraper` database. The database is managed by the [`infra`](../infra) repo.

Connect from a local client (DBeaver, psql, TablePlus, etc.):

```
Host:     localhost
Port:     5432
Database: job_scraper
User:     job_scraper
Password: <POSTGRES_PASSWORD from infra/.env>
```

## Database Schema

Jobs are deduplicated on `cipher` (Upwork's unique job ID). The schema lives in [`resources/db/migrations/001_create_jobs_table.sql`](resources/db/migrations/001_create_jobs_table.sql).

| Column            | Type        | Description |
|-------------------|-------------|-------------|
| `id`              | SERIAL PK   | Auto-increment row ID |
| `cipher`          | TEXT UNIQUE | Deduplication key — Upwork's unique job ID |
| `title`           | TEXT        | Job title |
| `description`     | TEXT        | Full job description |
| `link`            | TEXT        | URL to the job posting |
| `skills`          | TEXT[]      | Required skills (array) |
| `published_date`  | TIMESTAMPTZ | When the job was posted on Upwork |
| `job_type`        | TEXT        | `hourly` or `fixed` |
| `is_hourly`       | BOOLEAN     | Hourly flag |
| `hourly_low`      | INTEGER     | Minimum hourly rate |
| `hourly_high`     | INTEGER     | Maximum hourly rate |
| `budget`          | INTEGER     | Fixed price budget |
| `duration_weeks`  | INTEGER     | Expected project timeline in weeks |
| `contractor_tier` | TEXT        | Experience level required |
| `scraped_at`      | TIMESTAMPTZ | When this row was first inserted (default: now) |
| `last_seen`       | TIMESTAMPTZ | When this job was most recently seen in a scrape cycle |

Indexes: `published_date DESC`, `scraped_at DESC`, `last_seen DESC`.

`scraped_at` is set once on insert and never changes. `last_seen` is updated to `NOW()` every time the same job is seen again, so `last_seen - scraped_at` tells you how long a job has been on the market.

## Proxies

- The proxy list is downloaded from Webshare at startup and refreshed automatically every hour
- Each concurrent page fetch uses a randomly selected proxy from the list
- Token fetch retries also rotate proxies — if one IP is blocked by Cloudflare, the next retry picks a different one
- **402 from proxy**: Webshare quota exhausted — wait for monthly reset or upgrade plan
- **403 from Upwork**: Proxy IP flagged by Cloudflare — with enough proxies in the pool, retries will succeed

## Error Handling & Backoff

| Error | Behaviour |
|-------|-----------|
| Token fetch fails (403, network error) | Retry up to 3 times with different proxies, then back off 5 min |
| Token expired mid-cycle (401) | Invalidate and re-fetch immediately; back off 5 min after 3 consecutive expiries |
| Individual page fetch fails | Log warning, skip that page, continue with remaining pages |
| Any other exception | Log error, back off 30 seconds |

## Key Design Choices

- **`curl_cffi` for everything** — Chrome TLS fingerprint matching bypasses Cloudflare for both the token fetch and API calls. No browser needed.
- **`visitor_gql_token` over `UniversalSearchNuxt_vt`** — The main Upwork page sets the token directly in cookies, avoiding the search page which has heavier CF protection.
- **Per-retry proxy rotation on token fetch** — Each of the 3 token fetch attempts picks a fresh random proxy, so a single blocked IP doesn't exhaust all retries.
- **Bulk scrape on first run** — On an empty database the scraper fetches everything reachable (~100 pages) before switching to incremental cycles.
- **psycopg3 with ConnectionPool** — Lazy init, opened and closed by the controller.
- **Raw SQL, no ORM** — Direct psycopg3 with parameterized queries.
- **`ON CONFLICT (cipher) DO NOTHING`** — Silent deduplication; re-scraping the same jobs is harmless.

## Stack

- Python 3.13
- `curl_cffi` (Chrome TLS impersonation)
- `psycopg[binary,pool]` 3.2+
- `pydantic` 2+
- PostgreSQL 17
- Docker + Docker Compose
