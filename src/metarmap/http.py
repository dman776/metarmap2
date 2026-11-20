"""
One HTTP session for every outgoing request, so the TLS setup is paid once and not on every request.

requests.get builds a new Session each time, and urllib3 1.26 (the one the Pi has) parses the whole CA bundle for
every new connection: 1.4 s of CPU on a Pi Zero W, which put ssl_wrap_socket at half the time of a METAR fetch burst.
The Session here keeps its connections alive and hands urllib3 one SSL context with the CA bundle already loaded.
"""

import http.cookiejar
import ipaddress
import os
import ssl
import threading
import urllib.parse
import urllib.request

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import ReadTimeoutError
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


class _StaleConnectionRetry(Retry):
    """
    One retry, for a pooled connection the server closed while it sat idle (urllib3 counts that as a read error).
    Nothing else is tried again, as before the shared Session: not a connection that can't be made (connect=0: a
    network that drops packets would double the wait), a read timeout (a slow server: same), a certificate that fails
    (other=0), or a 429/503's Retry-After (respect_retry_after_header=False: urllib3 would sleep that long, uncapped,
    and send again behind the back of a caller that paces itself, like the planner's airport search).
    """

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        if isinstance(error, ReadTimeoutError):
            raise error  # what urllib3 does when there are no read retries left
        return super().increment(method, url, response, error, _pool, _stacktrace)


def _adapter() -> HTTPAdapter:
    """The https adapter of the shared Session. Pool: the planner's 8 workers and a feed or two on the same host."""
    retry = _StaleConnectionRetry(total=1, connect=0, other=0, respect_retry_after_header=False)
    return _PreloadedAdapter(pool_maxsize=12, max_retries=retry)


def _new_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _adapter())
    # no cookies, as requests.get kept none: tfr.faa.gov sets some, and merging the jar isn't thread-safe
    s.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
    return s


def session() -> requests.Session:
    global _session
    with _lock:
        if _session is None:
            _session = _new_session()
        return _session


def _plain(url, kwargs) -> bool:
    """
    Whether the shared Session's context is right for this request: the default certifi bundle, no proxy, a host name.
    A custom bundle (verify=<path>, REQUESTS_CA_BUNDLE) or verify=False would change the one shared context for every
    later request, and a proxy has no preloaded context, so those go through requests.get as they always did. So does
    an address given as an IP (a Kokoro server on the network): over https urllib3 1.26 sends no server name for one,
    and a context that checks host names, like the shared one, then refuses to connect at all.
    """
    if _is_ip(urllib.parse.urlsplit(url).hostname):
        return False
    if kwargs.get("verify", True) is not True or kwargs.get("proxies") or kwargs.get("cert"):
        return False
    if os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE"):
        return False
    return not urllib.request.getproxies()


def _is_ip(host) -> bool:
    try:
        ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return True


def get(url, **kwargs) -> requests.Response:
    """requests.get over the shared Session; a request that needs its own TLS settings goes through requests.get."""
    if not _plain(url, kwargs):
        return requests.get(url, **kwargs)
    return session().get(url, **kwargs)


def post(url, **kwargs) -> requests.Response:
    """requests.post over the shared Session; a request that needs its own TLS settings goes through requests.post."""
    if not _plain(url, kwargs):
        return requests.post(url, **kwargs)
    return session().post(url, **kwargs)
