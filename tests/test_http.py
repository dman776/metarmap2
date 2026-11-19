"""The shared HTTP session: one Session, and connections that don't load the CA bundle again."""

import ssl

import requests

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
    assert http.session().get_adapter("https://x.test/").max_retries.total == 1


def test_own_tls_settings_do_not_touch_the_shared_context(monkeypatch):
    for var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(http.urllib.request, "getproxies", lambda: {})
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
