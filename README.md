# Upwork Job Scraper

A lightweight scraper that continuously fetches public Upwork job listings via their GraphQL API and stores them in PostgreSQL. Uses `curl_cffi` with Chrome TLS fingerprint impersonation to bypass Cloudflare — no browser, no Selenium, no Lambda, no Kafka.

## How It Works

1. `curl_cffi` hits `https://www.upwork.com/` with `impersonate="chrome"` through a Webshare proxy and extracts the `visitor_gql_token` cookie.
2. That cookie is used as a Bearer token against Upwork's GraphQL API (`/api/graphql/v1`).
3. Results are paginated (default: 3 pages × 50 jobs = 150 jobs per cycle) and inserted into PostgreSQL with `ON CONFLICT (cipher) DO NOTHING` for dedup.
4. Sleeps `SCRAPE_INTERVAL` seconds, repeats.

## Architecture

```
src/
├── auth/token_manager.py            # Fetch + cache visitor_gql_token
├── controllers/scraper_controller.py # Main loop, signal handling, retry/backoff
├── errors/base_errors.py             # TokenExpired, TokenFetchFailed
├── log/log_config.py                 # Structured logging setup
├── models/
│   ├── job_models.py                 # Pydantic models for GraphQL response
│   └── proxy_models.py               # ProxyConfig
├── postgres/
│   ├── core.py                       # psycopg3 ConnectionPool
│   └── jobs.py                       # insert_jobs(), get_job_count()
├── proxies/proxy_manager.py          # WebshareProxyManager (loads + rotates)
├── scrapers/job_fetcher.py           # GraphQL query + pagination
└── settings/config.py                # Env var loading
```

## Running

Everything runs via Docker Compose.

```bash
# 1. Create .env
cp .env.example .env
# Edit .env with your real WEBSHARE_URL and POSTGRES_PASSWORD

# 2. Bring up the database and run the migration
docker compose up -d db
docker compose exec -T db psql -U upwork -d upwork < resources/db/migrations/001_create_jobs_table.sql

# 3. Start the scraper
docker compose up -d

# 4. Watch it work
docker compose logs -f scraper

# 5. Stop
docker compose down
```

## Environment Variables

| Variable            | Required | Default | Description                                      |
|---------------------|----------|---------|--------------------------------------------------|
| `DATABASE_URL`      | Yes      | —       | PostgreSQL connection string                     |
| `WEBSHARE_URL`      | Yes      | —       | Webshare proxy list download URL                 |
| `POSTGRES_PASSWORD` | Yes      | —       | PostgreSQL password (used in compose)            |
| `SCRAPE_INTERVAL`   | No       | 120     | Seconds between scrape cycles                    |
| `MAX_PAGES`         | No       | 3       | Pages to fetch per cycle (50 jobs/page)          |

## Database

All DDL lives in `resources/db/migrations/` and is run manually via `psql`. The application only does DML (INSERT/SELECT). The schema is a single `jobs` table with `cipher` as a unique key for dedup and `scraped_at` / `published_date` indexed for time-based queries.

## Key Design Choices

- **`curl_cffi` for everything** — Chrome TLS fingerprint matching bypasses Cloudflare for both the token fetch and the API calls. No browser needed.
- **`visitor_gql_token` over `UniversalSearchNuxt_vt`** — The main Upwork page returns `visitor_gql_token` directly in cookies, no search page (which has extra CF protection) required.
- **Same proxy for token + API** — The token is tied to the egress IP, so the proxy that fetches it must also be used for the subsequent API calls.
- **psycopg3 with ConnectionPool** — Lazy init, opened/closed by the controller.
- **Raw SQL, no ORM** — Direct psycopg3 with parameterized queries.
- **`ON CONFLICT (cipher) DO NOTHING`** — Dedup on Upwork's job cipher.

## Stack

- Python 3.13
- `curl_cffi` (Chrome TLS impersonation)
- `psycopg[binary,pool]` 3.2+
- `pydantic` 2+
- PostgreSQL 17
- Docker + Docker Compose
