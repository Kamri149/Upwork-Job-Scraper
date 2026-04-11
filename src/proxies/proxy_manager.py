import logging
import random
import threading
import time

from curl_cffi import requests as cffi_requests

from src.models.proxy_models import ProxyConfig
from src.settings.config import WEBSHARE_URL

LOGGER = logging.getLogger(__name__)

PROXY_REFRESH_INTERVAL = 3600  # Reload proxy list every hour


class WebshareProxyManager:

    def __init__(self):
        self._lock = threading.Lock()
        self._proxies: list[ProxyConfig] = []
        self._last_loaded: float = 0
        self.load_proxies()

    def _fetch_proxy_list(self) -> list[ProxyConfig]:
        """Fetch proxy list from Webshare (no lock held — pure I/O)."""
        resp = cffi_requests.get(WEBSHARE_URL, timeout=15)
        resp.raise_for_status()

        proxies = []
        for line in resp.text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            host, port, username, password = line.split(":", 3)
            proxies.append(
                ProxyConfig(host=host, port=int(port), username=username, password=password)
            )
        return proxies

    def load_proxies(self):
        proxies = self._fetch_proxy_list()
        with self._lock:
            self._proxies = proxies
            self._last_loaded = time.monotonic()
        LOGGER.info("Loaded %d proxies from Webshare", len(proxies))

    def get_proxy(self) -> ProxyConfig:
        if time.monotonic() - self._last_loaded > PROXY_REFRESH_INTERVAL:
            with self._lock:
                # Double-check inside lock so only one thread refreshes
                if time.monotonic() - self._last_loaded > PROXY_REFRESH_INTERVAL:
                    try:
                        proxies = self._fetch_proxy_list()
                        self._proxies = proxies
                        self._last_loaded = time.monotonic()
                        LOGGER.info("Refreshed %d proxies from Webshare", len(proxies))
                    except Exception:
                        LOGGER.warning("Failed to refresh proxy list, using cached")
                        self._last_loaded = time.monotonic() - PROXY_REFRESH_INTERVAL + 300

        with self._lock:
            if not self._proxies:
                raise RuntimeError("No proxies available")
            return random.choice(self._proxies)
