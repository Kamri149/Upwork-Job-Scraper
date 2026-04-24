import logging
import signal
import threading

from src.auth.token_manager import TokenManager
from src.errors.base_errors import TokenExpired, TokenFetchFailed
from src.postgres.core import close_pool, open_pool
from src.postgres.jobs import get_job_count, has_jobs, insert_jobs
from src.proxies.proxy_manager import WebshareProxyManager
from src.scrapers.job_fetcher import fetch_all_jobs
from src.settings.config import MAX_PAGES, SCRAPE_INTERVAL

LOGGER = logging.getLogger(__name__)

BULK_PAGES = 1000  # First run: grab everything reachable
_shutdown = threading.Event()


def _handle_signal(sig, _frame):
    LOGGER.info("Received signal %s, shutting down...", signal.Signals(sig).name)
    _shutdown.set()


def _scrape_cycle(token_mgr, proxy_mgr, max_pages):
    token = token_mgr.get_token(proxy_mgr=proxy_mgr)
    jobs = fetch_all_jobs(token, proxy_mgr, max_pages=max_pages)

    if jobs:
        insert_jobs(jobs)
        total = get_job_count()
        LOGGER.info("Submitted %d jobs for insert (%d total in DB)", len(jobs), total)
    else:
        LOGGER.warning("No jobs fetched this cycle")


def run():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    LOGGER.info(
        "Starting Upwork job scraper (interval=%ds, max_pages=%d)",
        SCRAPE_INTERVAL,
        MAX_PAGES,
    )

    proxy_mgr = WebshareProxyManager()
    token_mgr = TokenManager()
    open_pool()

    first_run = not has_jobs()
    token_retry_count = 0

    try:
        while not _shutdown.is_set():
            pages = BULK_PAGES if first_run else MAX_PAGES

            try:
                if first_run:
                    LOGGER.info("Initial bulk scrape: fetching up to %d pages...", pages)

                _scrape_cycle(token_mgr, proxy_mgr, pages)
                first_run = False
                token_retry_count = 0

            except TokenExpired:
                token_retry_count += 1
                LOGGER.warning("Token expired, refreshing... (attempt %d)", token_retry_count)
                token_mgr.invalidate()
                if token_retry_count >= 3:
                    LOGGER.error("Token expired %d times in a row, backing off 5 min", token_retry_count)
                    _shutdown.wait(300)
                    token_retry_count = 0
                continue

            except TokenFetchFailed:
                LOGGER.exception("Token fetch failed, backing off 5 min")
                _shutdown.wait(300)
                continue

            except Exception:
                LOGGER.exception("Error during scrape cycle")
                _shutdown.wait(30)
                continue

            _shutdown.wait(SCRAPE_INTERVAL)
    finally:
        close_pool()

    LOGGER.info("Shutting down gracefully")


if __name__ == "__main__":
    from src.log.log_config import init_logger

    init_logger()
    run()
