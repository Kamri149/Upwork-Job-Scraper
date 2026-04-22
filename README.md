# Upwork Job Scraper

Long-running Docker service that continuously fetches public Upwork job listings via their GraphQL API and stores them in PostgreSQL. Uses `curl_cffi` with Chrome TLS fingerprint impersonation to bypass Cloudflare — no browser, no Selenium, no Lambda, no Kafka.

## Architecture

```
src/
├── auth/token_manager.py              # Fetch + cache visitor_gql_token
├── controllers/scraper_controller.py  # Main loop, signal handling, retry/backoff
├── errors/base_errors.py              # TokenExpired, TokenFetchFailed
├── log/log_config.py                  # init_logger() with MaxLevelFilter
├── models/
│   ├── job_models.py                  # Pydantic models for GraphQL response
│   └── proxy_models.py                # ProxyConfig with to_curl_cffi_dict()
├── postgres/
│   ├── core.py                        # ConnectionPool (psycopg3), get_connection()
│   └── jobs.py                        # insert_jobs(), get_job_count()
├── proxies/proxy_manager.py           # WebshareProxyManager — loads and rotates proxies
├── scrapers/job_fetcher.py            # GraphQL query + pagination
└── settings/config.py                 # All env vars
```

## How It Works

1. `curl_cffi` hits `https://www.upwork.com/` with `impersonate="chrome"` through a Webshare proxy and extracts the `visitor_gql_token` cookie
2. That cookie is used as a Bearer token against Upwork's GraphQL API (`/api/graphql/v1`)
3. Results are paginated (default: 3 pages × 50 jobs = 150 jobs per cycle) using a `ThreadPoolExecutor` for concurrent page fetches
4. Jobs are inserted into PostgreSQL with `ON CONFLICT (cipher) DO NOTHING` for deduplication
5. The scraper sleeps `SCRAPE_INTERVAL` seconds then repeats

## Environment Variables

| Variable            | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `DATABASE_URL`      | Yes      | —       | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Yes      | —       | PostgreSQL password (used by Docker Compose) |
| `WEBSHARE_URL`      | Yes      | —       | Webshare proxy list download URL |
| `SCRAPE_INTERVAL`   | No       | 120     | Seconds to sleep between scrape cycles |
| `MAX_PAGES`         | No       | 3       | Pages to fetch per cycle (50 jobs/page) |

## Setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values — `POSTGRES_PASSWORD`, `DATABASE_URL`, and `WEBSHARE_URL` are all required.

### 2. Start the database

```bash
docker compose up -d db
```

### 3. Run the migration

```bash
docker compose exec -T db psql -U upwork -d upwork < resources/db/migrations/001_create_jobs_table.sql
```

### 4. Start the scraper

```bash
docker compose up -d scraper
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

# Check scraper and DB status
docker compose ps
```

### Database

```bash
# Connect to the database interactively
docker compose exec db psql -U upwork -d upwork

# Count all scraped jobs
docker compose exec db psql -U upwork -d upwork -c "SELECT COUNT(*) FROM jobs;"

# Jobs by type
docker compose exec db psql -U upwork -d upwork -c "SELECT job_type, COUNT(*) FROM jobs GROUP BY job_type ORDER BY count DESC;"

# Most recently scraped jobs
docker compose exec db psql -U upwork -d upwork -c "SELECT title, job_type, published_date FROM jobs ORDER BY scraped_at DESC LIMIT 20;"

# Jobs scraped in the last 24 hours
docker compose exec db psql -U upwork -d upwork -c "SELECT COUNT(*) FROM jobs WHERE scraped_at >= NOW() - INTERVAL '24 hours';"

# Export all jobs to CSV
docker compose exec db psql -U upwork -d upwork -c "\COPY (SELECT * FROM jobs) TO STDOUT WITH CSV HEADER" > jobs.csv
```

### Control

```bash
# Stop everything
docker compose down

# Stop and wipe the database volume (destructive — deletes all data)
docker compose down -v

# Restart just the scraper (e.g. after a config change)
docker compose restart scraper

# Rebuild the scraper image (e.g. after a code change) then restart
docker compose build scraper && docker compose up -d scraper
```

## Ports

The Postgres container is exposed on **host port 5432**. To connect from a local client (DBeaver, psql, etc.):

```
Host:     localhost
Port:     5432
Database: upwork
User:     upwork
Password: <POSTGRES_PASSWORD from .env>
```

## Database Schema

Jobs are deduplicated on `cipher` (Upwork's unique job ID). Key columns:

| Column           | Type        | Description |
|------------------|-------------|-------------|
| `cipher`         | TEXT UNIQUE | Deduplication key — Upwork's job ID |
| `title`          | TEXT        | Job title |
| `description`    | TEXT        | Full job description |
| `link`           | TEXT        | URL to the job posting |
| `skills`         | TEXT[]      | Required skills (array) |
| `published_date` | TIMESTAMPTZ | When the job was posted on Upwork |
| `job_type`       | TEXT        | `hourly` or `fixed` |
| `is_hourly`      | BOOLEAN     | Hourly flag |
| `hourly_low`     | INTEGER     | Minimum hourly rate |
| `hourly_high`    | INTEGER     | Maximum hourly rate |
| `budget`         | INTEGER     | Fixed price budget |
| `duration_weeks` | INTEGER     | Expected project duration in weeks |
| `contractor_tier`| TEXT        | Experience level required |
| `scraped_at`     | TIMESTAMPTZ | When this row was inserted |

Full schema: [`resources/db/migrations/001_create_jobs_table.sql`](resources/db/migrations/001_create_jobs_table.sql)

## Proxies

A proxy is randomly selected from the Webshare list for each token fetch and API call. The same proxy is used for both — the token is tied to the egress IP. The proxy list is refreshed automatically every hour.

## Key Design Choices

- **`curl_cffi` for everything** — Chrome TLS fingerprint matching bypasses Cloudflare for both the token fetch and API calls. No browser needed.
- **`visitor_gql_token` over `UniversalSearchNuxt_vt`** — The main Upwork page returns the token directly in cookies, bypassing the search page which has extra CF protection.
- **Same proxy for token + API** — The token is tied to the egress IP, so the proxy that fetches it must also be used for subsequent API calls.
- **psycopg3 with ConnectionPool** — Lazy init, opened and closed by the controller.
- **Raw SQL, no ORM** — Direct psycopg3 with parameterized queries.
- **`ON CONFLICT (cipher) DO NOTHING`** — Silent deduplication on Upwork's job cipher.
