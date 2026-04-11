# Upwork Job Scraper

## What This Is

Scraper that fetches anonymous Upwork job listings via their GraphQL API and stores them in PostgreSQL. Uses curl_cffi with TLS fingerprint impersonation (`impersonate="chrome"`) both to obtain a visitor token and to query the API.

## Architecture

```
src/
├── auth/token_manager.py       # curl_cffi: hit upwork.com, extract visitor_gql_token cookie
├── controllers/scraper_controller.py  # Main loop with signal handling
├── errors/base_errors.py       # TokenExpired, TokenFetchFailed
├── log/log_config.py           # init_logger() with MaxLevelFilter
├── models/
│   ├── job_models.py           # Job, JobList — Pydantic models for GraphQL response
│   └── proxy_models.py         # ProxyConfig with to_curl_cffi_dict()
├── postgres/
│   ├── core.py                 # ConnectionPool (psycopg_pool), get_connection()
│   └── jobs.py                 # insert_jobs(), get_job_count()
├── proxies/proxy_manager.py    # WebshareProxyManager — loads and rotates proxies
├── scrapers/job_fetcher.py     # GraphQL query, fetch_jobs_page(), fetch_all_jobs()
└── settings/config.py          # All env vars: DATABASE_URL, WEBSHARE_URL, etc.
```

## How It Works

1. curl_cffi hits `https://www.upwork.com/` with `impersonate="chrome"` via Webshare proxy → gets `visitor_gql_token` cookie
2. Uses that cookie as Bearer token to query Upwork's GraphQL API (`/api/graphql/v1`)
3. Paginates through results (default: 3 pages × 50 jobs = 150 jobs/cycle)
4. Inserts into PostgreSQL with `ON CONFLICT (cipher) DO NOTHING` for dedup
5. Sleeps `SCRAPE_INTERVAL` seconds (default 120), repeats

## Running

Everything runs via Docker:

```bash
# Create .env from example
cp .env.example .env
# Edit .env with real WEBSHARE_URL and POSTGRES_PASSWORD

# Run the migration
docker compose up -d db
docker compose exec -T db psql -U upwork -d upwork < resources/db/migrations/001_create_jobs_table.sql

# Start scraper
docker compose up -d

# Check logs
docker compose logs -f scraper

# Stop
docker compose down
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `WEBSHARE_URL` | Yes | — | Webshare proxy list download URL |
| `POSTGRES_PASSWORD` | Yes | — | PostgreSQL password (used in compose) |
| `SCRAPE_INTERVAL` | No | 120 | Seconds between scrape cycles |
| `MAX_PAGES` | No | 3 | Pages to fetch per cycle (50 jobs/page) |

## Key Decisions

- **curl_cffi for everything**: TLS fingerprint matching via `impersonate="chrome"` bypasses Cloudflare for both token and API calls — no browser needed
- **visitor_gql_token over UniversalSearchNuxt_vt**: The main Upwork page returns `visitor_gql_token` cookie directly, no search page (which has extra CF protection) needed
- **psycopg3 with ConnectionPool**: Lazy init (`open=False`), opened/closed by controller
- **No browser, no Kafka, no Lambda, no Selenium**: Pure HTTP with curl_cffi
- **Raw SQL, no ORM**: Direct psycopg3 with parameterized queries
- **`ON CONFLICT (cipher) DO NOTHING`**: Dedup on job cipher (unique ID from Upwork)
- **Same proxy for token + API**: Token is fetched through the same Webshare proxy used for API calls

## Database Migrations

All DDL lives in `resources/db/migrations/`. Run manually via psql — Python only does DML.

## Docker Details

- **Base image**: `python:3.13-slim` (lightweight, no browser dependencies)
- **Compose**: postgres:17 + scraper, postgres port bound to 0.0.0.0 (all interfaces)
- **Log rotation**: json-file driver with 50MB max-size, 3 files
