from unittest.mock import MagicMock, patch

import pytest

from src.models.proxy_models import ProxyConfig


class TestProxyConfig:

    def test_to_proxy_url(self):
        proxy = ProxyConfig(host="1.2.3.4", port=8080, username="user", password="pass")
        assert proxy.to_proxy_url() == "http://user:pass@1.2.3.4:8080"

    def test_to_curl_cffi_dict(self):
        proxy = ProxyConfig(host="1.2.3.4", port=8080, username="user", password="pass")
        d = proxy.to_curl_cffi_dict()
        assert d == {
            "http": "http://user:pass@1.2.3.4:8080",
            "https": "http://user:pass@1.2.3.4:8080",
        }

    def test_special_chars_in_password(self):
        proxy = ProxyConfig(host="proxy.io", port=3128, username="u", password="p@ss:word")
        assert proxy.to_proxy_url() == "http://u:p@ss:word@proxy.io:3128"


PROXY_RESPONSE = """
1.2.3.4:8080:user1:pass1
5.6.7.8:9090:user2:pass2

10.0.0.1:3128:user3:pass3
"""


class TestWebshareProxyManager:

    @patch("src.proxies.proxy_manager.cffi_requests")
    def test_load_proxies_parses_lines(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.text = PROXY_RESPONSE
        mock_requests.get.return_value = mock_resp

        from src.proxies.proxy_manager import WebshareProxyManager
        mgr = WebshareProxyManager()

        assert len(mgr._proxies) == 3
        assert mgr._proxies[0].host == "1.2.3.4"
        assert mgr._proxies[0].port == 8080
        assert mgr._proxies[1].username == "user2"
        assert mgr._proxies[2].password == "pass3"

    @patch("src.proxies.proxy_manager.cffi_requests")
    def test_get_proxy_returns_valid_proxy(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.text = "1.2.3.4:8080:user:pass"
        mock_requests.get.return_value = mock_resp

        from src.proxies.proxy_manager import WebshareProxyManager
        mgr = WebshareProxyManager()
        proxy = mgr.get_proxy()

        assert isinstance(proxy, ProxyConfig)
        assert proxy.host == "1.2.3.4"

    @patch("src.proxies.proxy_manager.cffi_requests")
    def test_skips_blank_lines(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.text = "\n\n1.2.3.4:8080:u:p\n\n"
        mock_requests.get.return_value = mock_resp

        from src.proxies.proxy_manager import WebshareProxyManager
        mgr = WebshareProxyManager()

        assert len(mgr._proxies) == 1

    @patch("src.proxies.proxy_manager.cffi_requests")
    def test_raises_when_no_proxies(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_requests.get.return_value = mock_resp

        from src.proxies.proxy_manager import WebshareProxyManager
        mgr = WebshareProxyManager()

        with pytest.raises(RuntimeError, match="No proxies"):
            mgr.get_proxy()
