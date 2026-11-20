"""The shared HTTP session: one Session, and connections that don't load the CA bundle again."""

import contextlib
import socket
import ssl
import threading
import time
from pathlib import Path

import pytest
import requests
import urllib3.util.connection

from metarmap import http


def test_session_is_shared():
    assert http.session() is http.session()


def test_https_adapter_shares_one_ssl_context():
    adapter = http.session().get_adapter("https://aviationweather.gov/")
    assert isinstance(adapter, http._PreloadedAdapter)
    assert adapter.poolmanager.connection_pool_kw["ssl_context"] is adapter._context
    assert adapter._context.verify_mode == ssl.CERT_REQUIRED
    assert adapter._context.check_hostname


def test_verified_connection_does_not_reload_the_bundle():
    adapter = http.session().get_adapter("https://aviationweather.gov/")
    url = "https://aviationweather.gov/"
    if hasattr(adapter, "get_connection_with_tls_context"):  # requests 2.32 and later
        conn = adapter.get_connection_with_tls_context(requests.Request("GET", url).prepare(), True)
    else:
        conn = adapter.get_connection(url)
    adapter.cert_verify(conn, "https://aviationweather.gov/", True, None)
    assert conn.ca_certs is None and conn.ca_cert_dir is None
    assert conn.cert_reqs == "CERT_REQUIRED"


def test_get_goes_through_the_session(monkeypatch):
    asked = []
    monkeypatch.setattr(http.session(), "get", lambda url, **kw: asked.append((url, kw)) or "answer")
    assert http.get("https://x.test/", timeout=3) == "answer"
    assert asked == [("https://x.test/", {"timeout": 3})]


def test_a_stale_pooled_connection_is_retried_once():
    retry = http.session().get_adapter("https://x.test/").max_retries
    assert retry.total == 1 and retry.connect == 0 and retry.other == 0 and not retry.respect_retry_after_header


@pytest.fixture
def plain_env(monkeypatch):
    """No CA bundle in the environment and no proxy: http.get and http.post use the shared Session."""
    for var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(http.urllib.request, "getproxies", lambda: {})


def test_own_tls_settings_do_not_touch_the_shared_context(monkeypatch, plain_env):
    asked = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: asked.append(kw) or "plain")
    monkeypatch.setattr(http.session(), "get", lambda url, **kw: "shared")
    assert http.get("https://x.test/") == "shared"
    assert http.get("https://x.test/", verify=True) == "shared"
    assert http.get("https://x.test/", verify=False) == "plain"  # never downgrades the shared context
    assert http.get("https://x.test/", verify="/some/bundle.pem") == "plain"
    assert http.get("https://x.test/", proxies={"https": "http://p:3128"}) == "plain"
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/corp.pem")
    assert http.get("https://x.test/") == "plain"
    monkeypatch.delenv("REQUESTS_CA_BUNDLE")
    monkeypatch.setattr(http.urllib.request, "getproxies", lambda: {"https": "http://p:3128"})
    assert http.get("https://x.test/") == "plain"
    assert len(asked) == 5


def test_post_goes_through_the_session_unless_it_has_its_own_tls_settings(monkeypatch, plain_env):
    asked = []
    monkeypatch.setattr(requests, "post", lambda url, **kw: asked.append(kw) or "plain")
    monkeypatch.setattr(http.session(), "post", lambda url, **kw: "shared")
    assert http.post("https://x.test/", json={"a": 1}, timeout=3) == "shared"
    assert http.post("https://x.test/", verify=False) == "plain"
    assert http.post("https://x.test/", verify="/some/bundle.pem") == "plain"
    assert http.post("https://x.test/", proxies={"https": "http://p:3128"}) == "plain"
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/corp.pem")
    assert http.post("https://x.test/") == "plain"
    assert len(asked) == 4


def test_an_address_given_as_an_ip_does_not_use_the_shared_context(monkeypatch, plain_env):
    """urllib3 1.26 sends no server name for an IP, and the shared context (which checks host names) refuses it."""
    monkeypatch.setattr(requests, "get", lambda url, **kw: "plain")
    monkeypatch.setattr(requests, "post", lambda url, **kw: "plain")
    monkeypatch.setattr(http.session(), "get", lambda url, **kw: "shared")
    monkeypatch.setattr(http.session(), "post", lambda url, **kw: "shared")
    assert http.post("https://192.168.0.164:8880/v1/audio/speech") == "plain"
    assert http.get("https://[::1]:8443/") == "plain"
    assert http.get("https://kokoro.local:8880/") == "shared"
    assert http.post("https://aviationweather.gov/") == "shared"


# ---- against a TLS server on this machine (no network) --------------------------------------------------------------
# untrusted_tls.pem is a self-signed key and certificate for localhost and 127.0.0.1, made with
#   openssl req -x509 -newkey rsa:2048 -nodes -days 36500 -subj /CN=localhost \
#     -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" -keyout key.pem -out cert.pem; cat key.pem cert.pem
UNTRUSTED_PEM = str(Path(__file__).parent / "fixtures" / "untrusted_tls.pem")


@contextlib.contextmanager
def tls_server(answer):
    """
    A TLS server on 127.0.0.1 with untrusted_tls.pem. For each request it reads it calls answer(connection number,
    request number on that connection) and sends what that returns (None: hangs up without answering). Yields
    (port, log): log gets ("connect", n) for each connection, ("request", n, k) for each request read.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(UNTRUSTED_PEM)
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.05)  # so the accept loop sees stop: close() doesn't wake a blocked accept() on Linux
    stop, log, threads, connections = threading.Event(), [], [], []

    def handle(conn, n):
        with contextlib.suppress(ssl.SSLError, OSError), conn:
            conn.settimeout(5)
            with context.wrap_socket(conn, server_side=True) as tls, tls.makefile("rb") as reader:
                connections.append(tls)
                for k in range(1, 100):
                    if not reader.readline():  # the client closed the connection
                        return
                    while reader.readline() not in (b"\r\n", b""):
                        pass
                    log.append(("request", n, k))
                    reply = answer(n, k)
                    if reply is None:
                        return
                    tls.sendall(reply)

    def accept():
        n = 0
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            n += 1
            log.append(("connect", n))
            thread = threading.Thread(target=handle, args=(conn, n), daemon=True)
            threads.append(thread)
            thread.start()

    acceptor = threading.Thread(target=accept, daemon=True)
    acceptor.start()
    try:
        yield server.getsockname()[1], log
    finally:
        stop.set()
        acceptor.join(5)
        server.close()
        for conn in connections:  # a connection the client still holds open: its handler stops waiting for it
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
        for thread in threads:
            thread.join(5)


def trusting_session():
    """A Session made as the shared one is (adapter, retry, cookie policy), also trusting untrusted_tls.pem."""
    s = http._new_session()
    s.get_adapter("https://x.test/")._context.load_verify_locations(UNTRUSTED_PEM)
    return s


OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


def test_a_certificate_that_fails_verification_raises_at_once(monkeypatch, plain_env):
    """
    A self-signed certificate (not in certifi's bundle): the shared Session refuses it with an SSLError after one
    handshake. It is not tried again, never falls back to requests.get or an unverified connection, no request is
    sent, and the shared context still verifies afterwards.
    """
    plain = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: plain.append(kw))
    failed = pytest.raises(requests.exceptions.SSLError, match="CERTIFICATE_VERIFY_FAILED")
    with tls_server(lambda n, k: OK) as (port, log), failed:
        http.get(f"https://localhost:{port}/", timeout=5)
    assert plain == []
    assert log == [("connect", 1)]
    adapter = http.session().get_adapter("https://x.test/")
    assert adapter._context.verify_mode == ssl.CERT_REQUIRED and adapter._context.check_hostname


def test_a_stale_kept_alive_connection_is_asked_again_on_a_new_one():
    """The server takes the second request on the kept-alive connection and hangs up: it's sent again, and answered."""
    with tls_server(lambda n, k: None if (n, k) == (1, 2) else OK) as (port, log), trusting_session() as s:
        assert s.get(f"https://localhost:{port}/", timeout=5).text == "ok"
        assert s.get(f"https://localhost:{port}/", timeout=5).text == "ok"
    requests_sent = [entry for entry in log if entry[0] == "request"]
    assert requests_sent == [("request", 1, 1), ("request", 1, 2), ("request", 2, 1)]


def test_a_429_with_retry_after_comes_back_at_once():
    """urllib3 would sleep Retry-After and send again; the caller (the planner's rate gate) decides instead."""
    reply = b"HTTP/1.1 429 Too Many Requests\r\nRetry-After: 5\r\nContent-Length: 0\r\n\r\n"
    with tls_server(lambda n, k: reply) as (port, log), trusting_session() as s:
        started = time.monotonic()
        response = s.get(f"https://localhost:{port}/", timeout=5)
        took = time.monotonic() - started
    assert response.status_code == 429 and response.headers["Retry-After"] == "5"
    assert took < 2
    assert [entry for entry in log if entry[0] == "request"] == [("request", 1, 1)]


def test_a_read_timeout_is_not_asked_again():
    """A slow server: asking again would double the wait. It's a requests Timeout, after one request."""

    def slow(n, k):
        time.sleep(0.6)
        return OK

    with tls_server(slow) as (port, log), trusting_session() as s, pytest.raises(requests.exceptions.Timeout):
        s.get(f"https://localhost:{port}/", timeout=(5, 0.3))
    assert [entry for entry in log if entry[0] == "request"] == [("request", 1, 1)]


def test_a_connection_that_cannot_be_made_is_not_tried_again(monkeypatch):
    """A network that drops packets: one connect timeout, not two (a planner lookup's cancel waits on it)."""
    tries = []

    def unreachable(*args, **kwargs):
        tries.append(args[0])
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib3.util.connection, "create_connection", unreachable)
    with trusting_session() as s, pytest.raises(requests.exceptions.ConnectTimeout):
        s.get("https://aviationweather.gov/", timeout=1)
    assert tries == [("aviationweather.gov", 443)]


def test_the_session_keeps_no_cookies():
    """As requests.get kept none: tfr.faa.gov sets some, and merging a shared jar isn't thread-safe."""
    reply = b"HTTP/1.1 200 OK\r\nSet-Cookie: DR_SITE_PM=1; Path=/\r\nContent-Length: 2\r\n\r\nok"
    with tls_server(lambda n, k: reply) as (port, log), trusting_session() as s:
        response = s.get(f"https://localhost:{port}/", timeout=5)
        plain = requests.Session()  # the control: a Session's default policy keeps it
        plain.mount("https://", s.get_adapter("https://x.test/"))
        plain.get(f"https://localhost:{port}/", timeout=5)
    assert response.text == "ok" and response.headers["Set-Cookie"].startswith("DR_SITE_PM")
    assert len(s.cookies) == 0
    assert len(plain.cookies) == 1
    assert len(http.session().cookies) == 0
