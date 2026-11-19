"""
One HTTP session for every outgoing request, so the TLS setup is paid once and not on every request.

requests.get builds a new Session each time, and urllib3 1.26 (the one the Pi has) parses the whole CA bundle for
every new connection: 1.4 s of CPU on a Pi Zero W, which put ssl_wrap_socket at half the time of a METAR fetch burst.
The Session here keeps its connections alive and hands urllib3 one SSL context with the CA bundle already loaded.
"""

import os
import ssl
import threading
import urllib.request

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_lock = threading.Lock()
_session = None


class _PreloadedAdapter(HTTPAdapter):
    """An adapter whose connections share one SSLContext with the CA bundle loaded once."""

    def __init__(self, *args, **kwargs):
        self._context = ssl.create_default_context(cafile=certifi.where())
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, ssl_context=self._context, **kwargs)

    def cert_verify(self, conn, url, verify, cert):
        super().cert_verify(conn, url, verify, cert)
        if verify is True:
            # the context has the bundle: without this urllib3 loads certifi's file again for each connection
            conn.ca_certs = None
            conn.ca_cert_dir = None


def session() -> requests.Session:
    global _session
    with _lock:
        if _session is None:
            s = requests.Session()
            adapter = _PreloadedAdapter(pool_maxsize=8, max_retries=Retry(total=1))
            s.mount("https://", adapter)
            _session = s
        return _session


def _plain(kwargs) -> bool:
    """
    Whether the shared Session's context is right for this request: the default certifi bundle, no proxy. A custom
    bundle (verify=<path>, REQUESTS_CA_BUNDLE) or verify=False would change the one shared context for every later
    request, and a proxy has no preloaded context, so those go through requests.get as they always did.
    """
    if kwargs.get("verify", True) is not True or kwargs.get("proxies") or kwargs.get("cert"):
        return False
    if os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE"):
        return False
    return not urllib.request.getproxies()


def get(url, **kwargs) -> requests.Response:
    """requests.get over the shared Session; a request that needs its own TLS settings goes through requests.get."""
    if not _plain(kwargs):
        return requests.get(url, **kwargs)
    return session().get(url, **kwargs)
