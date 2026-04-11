import logging
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from src.settings.config import POSTGRES_URI

LOGGER = logging.getLogger(__name__)

CONNECTION_POOL = ConnectionPool(
    POSTGRES_URI,
    min_size=2,
    max_size=10,
    open=False,
    reconnect_timeout=0,  # Retry forever on DB connection loss
    max_lifetime=300,  # Recycle connections every 5 min to discard stale ones
)


def open_pool():
    CONNECTION_POOL.open()
    CONNECTION_POOL.wait()
    LOGGER.info("Connection pool opened")


def close_pool():
    CONNECTION_POOL.close()
    LOGGER.info("Connection pool closed")


@contextmanager
def get_connection():
    with CONNECTION_POOL.connection() as conn:
        yield conn
