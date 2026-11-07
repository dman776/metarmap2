"""
Digital ATIS (D-ATIS), the text the FAA publishes for about 75 large airports, from atis.info, for the spoken ATIS
(metarmap.atis_spoken, /api/atis/<code>.audio). On with speech.atis, under speech.enabled.

atis.info mirrors the FAA's D-ATIS as JSON: /api/all is every airport's, a list of
{"airport": "KIAH", "type": "combined" | "arr" | "dep", "code": "S", "datis": "IAH ATIS INFO S 1653Z. ...",
"time": "1653", "updatedAt": "..."}. An airport with separate arrival and departure ATIS has one entry for each. It
needs no key, but it's an unofficial service with no published terms, so the map asks politely: only when someone
wants an ATIS, one request for every airport, at most once a minute (FRESH_SECONDS), waiting longer after failures.
Which airports have one (for the ATIS buttons) is checked every half hour in the background while ATIS is on.
"""

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Set

import requests

from metarmap import USER_AGENT

log = logging.getLogger(__name__)

API_URL = "https://atis.info/api/all"
TIMEOUT = 10  # seconds
FRESH_SECONDS = 60  # an ATIS asked for is at most this old (they change about hourly, or for a special)
AVAILABLE_SECONDS = 30 * 60  # how often the list of airports with an ATIS is refreshed, in the background
MAX_BACKOFF = 600  # seconds: the longest wait after failed fetches
KINDS = ("combined", "arr", "dep")


class AtisError(Exception):
    """Why there's no ATIS. status: the HTTP status the API should answer with."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def parse(data) -> Dict[str, List[dict]]:
    """atis.info's /api/all as {airport: [entries]}; entries that aren't an ATIS are left out."""
    found: Dict[str, List[dict]] = {}
    for entry in data if isinstance(data, list) else ():
        if not isinstance(entry, dict):
            continue
        airport, text = str(entry.get("airport") or "").upper(), entry.get("datis")
        if not airport or not isinstance(text, str) or not text.strip():
            continue
        kind = entry.get("type") if entry.get("type") in KINDS else "combined"
        found.setdefault(airport, []).append(
            {
                "type": kind,
                "code": str(entry.get("code") or ""),
                "time": str(entry.get("time") or ""),
                "updatedAt": entry.get("updatedAt"),
                "datis": text,
            }
        )
    return found


class Atis:
    """
    enabled: returns whether spoken ATIS is on now (speech.enabled and speech.atis), so a change applies at once.
    get: requests.get, or a test's own. clock: epoch seconds. background: run the half-hourly refresh in a thread
    (tests run it in place).
    """

    def __init__(self, enabled: Callable[[], bool], get=None, clock=time.time, background=True):
        self._enabled = enabled
        self._get = get or requests.get
        self._clock = clock
        self._background = background
        self._fetching = threading.Lock()  # one fetch at a time
        self._lock = threading.Lock()
        self._data: Dict[str, List[dict]] = {}
        self._fetched: Optional[float] = None  # when the last fetch that worked was
        self._tried: Optional[float] = None  # when the last fetch started
        self._backoff = 0.0
        self._error: Optional[str] = None

    def enabled(self) -> bool:
        return bool(self._enabled())

    def entries(self, code: str) -> List[dict]:
        """
        The airport's ATIS entries, no older than FRESH_SECONDS if atis.info answers. Raises AtisError: 503 when
        spoken ATIS is off, 404 when the airport has no D-ATIS, 502 when atis.info can't be reached.
        """
        if not self.enabled():
            raise AtisError("Spoken ATIS is off: turn on speech.atis (Config > System > Spoken weather)", 503)
        self.refresh(FRESH_SECONDS, wait=True)
        with self._lock:
            data, fetched, error = self._data, self._fetched, self._error
        if fetched is None:
            raise AtisError(f"Couldn't get the ATIS: {error or 'atis.info has not answered'}")
        found = data.get(code.upper())
        if not found:
            raise AtisError(f"{code.upper()} has no digital ATIS", 404)
        return [dict(e) for e in found]

    def available(self) -> Set[str]:
        """The airports with an ATIS, as last fetched; empty while off. Never waits: a stale list is refreshed in
        the background."""
        if not self.enabled():
            return set()
        if self._due(AVAILABLE_SECONDS):
            if self._background:
                threading.Thread(target=self.refresh, args=(AVAILABLE_SECONDS,), daemon=True).start()
            else:
                self.refresh(AVAILABLE_SECONDS)
        with self._lock:
            return set(self._data)

    def _due(self, max_age: float) -> bool:
        now = self._clock()
        if self._tried is not None and now - self._tried < self._backoff:
            return False  # failing: wait
        return self._fetched is None or now - self._fetched >= max_age

    def refresh(self, max_age: float = FRESH_SECONDS, wait: bool = False):
        """Fetches if what's there is older than max_age. wait: wait for a fetch already running, for its answer."""
        if not self._due(max_age):
            return
        if not self._fetching.acquire(blocking=wait):
            return
        try:
            if self._due(max_age):  # another request may have fetched meanwhile
                self.fetch()
        finally:
            self._fetching.release()

    def fetch(self):
        """Asks atis.info for every airport's ATIS. Never raises: a failure keeps what was there."""
        self._tried = self._clock()
        try:
            response = self._get(API_URL, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            data = parse(response.json())
        except (requests.exceptions.RequestException, ValueError) as e:
            self._failed(f"couldn't reach atis.info: {e}")
            return
        with self._lock:
            self._data, self._fetched = data, self._tried
            self._backoff, self._error = 0.0, None
        log.debug(f"atis: {len(data)} airports")

    def _failed(self, error: str):
        if self._error != error:
            log.warning(f"atis: {error}")
        with self._lock:
            self._error = error
            self._backoff = min(MAX_BACKOFF, max(FRESH_SECONDS, 2 * self._backoff))
