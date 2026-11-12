"""
The spoken METARs (metarmap.spoken) as audio: /api/speak/<code>.audio. The words are read by a speech server on
another computer (speech.engine), so the Pi only sends the text and keeps the audio it gets back, as a WAV (16-bit
mono): it suits a Pi Zero W, which couldn't make speech itself.

  wyoming  Piper, over the Wyoming protocol: Home Assistant's Piper add-on, or any wyoming-piper server
           (speech.wyoming_host, port 10200). 16 or 22 kHz, by the voice
  kokoro   Kokoro-FastAPI (speech.kokoro_url, e.g. http://192.168.0.164:8880), over its OpenAI-style speech API:
           asked for raw PCM (24 kHz) and wrapped in a WAV here, as its own WAVs are written for streaming

Each clip is kept until its text changes (a new METAR, a new ATIS), so playing an airport again takes no time.

A slow or hung server costs one wait, not one per press:
  - each clip has speech.timeout seconds in all (connecting, reading, the whole answer): past it, a 504
  - two asks for the same clip at once make one: the second waits for the first, and gets its clip or its error
  - after a server didn't answer (a timeout, or it couldn't be reached), the map leaves it alone for 30 s, then 1, 2,
    4 and 5 minutes, answering 503 at once; a clip already made still plays, and the first clip made, or another
    server, voice, speed or time limit set, ends it. Clips asked for before the wait began that fail too don't make it
    longer. audio(force=True) (Config's Test, the Pronunciation speaker) asks anyway: a server just restarted
health() says how the last clip went (/api/live's speechOk and speechError).
"""

import hashlib
import io
import json
import logging
import math
import socket
import threading
import time
import wave
from collections import OrderedDict
from typing import Callable, Dict, Optional, Tuple

import requests
from urllib3.exceptions import ReadTimeoutError

from metarmap import USER_AGENT

log = logging.getLogger(__name__)

CACHE_BYTES = 32 * 1024 * 1024  # the clips kept in memory: a METAR is about 500 KB (15 s), an ATIS a few MB
WYOMING_VERSION = "1.5.0"  # the protocol version the map speaks (wyoming 1.5 and later understand it)
MAX_EVENT_BYTES = 4 * 1024 * 1024  # an audio chunk is a few KB; anything this big isn't a Wyoming server
KOKORO_RATE = 24000  # Kokoro's raw PCM: 16-bit mono at 24 kHz
CONNECT_SECONDS = 5  # to reach the server: on the same network it answers at once, or isn't there
SLOW_SECONDS = 10  # a clip that took longer is logged as a warning
FIRST_BACKOFF = 30  # seconds the map leaves a server that didn't answer alone, doubling each time it still doesn't
MAX_BACKOFF = 300
WAIT_GRACE = 1.0  # seconds a second ask for a clip waits past the first's time limit, for it to finish saying so
CHUNK_BYTES = 64 * 1024  # Kokoro's answer is read in these, the time limit checked between them
MAX_AUDIO_BYTES = 32 * 1024 * 1024  # the most of Kokoro's answer read: about 11 minutes, far past any ATIS


def configured(s) -> bool:
    """Whether speech is on, with a server named for its engine (the AWOS buttons and tab show then)."""
    return s.enabled and bool(s.kokoro_url if s.engine == "kokoro" else s.wyoming_host)


class SpeechError(Exception):
    """
    Why there's no audio. status: the HTTP status the API should answer with (503: no speech, or the server is left
    alone a while; 504: it didn't answer in time; 502: it failed). down: the server didn't answer (timed out, or
    couldn't be reached), so it's left alone a while.
    """

    def __init__(self, message: str, status: int = 502, down: bool = False):
        super().__init__(message)
        self.status = status
        self.down = down


def engine_name(s) -> str:
    return "Kokoro" if s.engine == "kokoro" else "Piper"


def timed_out(s, timeout: Optional[int] = None) -> SpeechError:
    return SpeechError(f"{engine_name(s)} didn't answer in {timeout or s.timeout} s", 504, down=True)


def server_of(s) -> tuple:
    """What a backoff and the health are about: another engine, server, voice, speed or time limit starts afresh."""
    return (
        s.engine,
        s.wyoming_host,
        s.wyoming_port,
        s.wyoming_voice,
        s.kokoro_url,
        s.kokoro_voice,
        s.kokoro_speed,
        s.timeout,
    )


class _Cutoff:
    """
    Shuts `sock` down when the time limit comes, from a timer thread, so a read blocked on it ends at once. A socket's
    own timeout is per read: a server sending a byte at a time never meets it, nor a buffered read waiting to fill
    (urllib3's read(amt), readline), so the time limit can't be checked between reads alone. No socket: no timer.
    Kokoro's answer only has one once its headers have come: headers sent slowly are limited per read alone.
    """

    def __init__(self, sock, seconds: float):
        self.fired = False
        self._sock = sock
        self._timer = threading.Timer(max(0.0, seconds), self._cut)
        self._timer.daemon = True

    def _cut(self):
        self.fired = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):  # closed already, or a stand-in without one
            pass

    def __enter__(self):
        if self._sock is not None:
            self._timer.start()
        return self

    def __exit__(self, *exc):
        self._timer.cancel()
        return False


class _Render:
    """A clip being made: a second ask for it waits on `done`, then takes `clip` or `error`."""

    def __init__(self, deadline: float, timeout: int):
        self.deadline, self.timeout = deadline, timeout
        self.done = threading.Event()
        self.clip: Optional[bytes] = None
        self.error = SpeechError("The speech couldn't be made")  # until it's made (an unexpected failure keeps it)


class Speech:
    """
    settings: returns the speech settings now (settings.SpeechSettings), so a change applies at once.
    connect: socket.create_connection, post: requests.post, clock: time.monotonic; stand-ins in tests.
    """

    def __init__(self, settings: Callable, connect=None, post=None, clock=None):
        self._settings = settings
        self._connect = connect or socket.create_connection
        self._post = post or requests.post
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()
        self._cached = 0  # bytes in the cache
        self._rendering: Dict[str, _Render] = {}  # the clips being made now, by cache key
        # how the last clip went, for the server it was asked of (server_of): ok None (none yet), True or False
        self._server: Optional[tuple] = None
        self._ok: Optional[bool] = None
        self._error = ""
        self._backoff = 0.0  # seconds the server is left alone after it didn't answer (0: it's asked)
        self._retry_at = 0.0  # self._clock() when it's asked again
        self._backoff_from = -math.inf  # self._clock() when that wait was set: clips asked before don't lengthen it

    def health(self) -> Tuple[Optional[bool], str]:
        """
        (ok, error) of the last clip made for the server set now: (None, "") before any; while the server is left
        alone, the line its 503 says. No I/O.
        """
        server = server_of(self._settings())
        with self._lock:
            if self._server != server:
                return None, ""
            return self._ok, self._waiting(self._clock()) or self._error

    def _waiting(self, now: float) -> str:
        """The 503's line while the server is left alone, else "". Under the lock."""
        if now >= self._retry_at:
            return ""
        return f"The speech server isn't answering; trying again in {math.ceil(self._retry_at - now)} s"

    def _same_server(self, server: tuple):
        """Another server, voice, speed or time limit set: its backoff and health start afresh. Under the lock."""
        if self._server != server:
            self._server, self._ok, self._error = server, None, ""
            self._backoff, self._retry_at, self._backoff_from = 0.0, 0.0, -math.inf

    def problem(self) -> Optional[str]:
        """Why the map can't speak (what to set up), or None if it can try."""
        s = self._settings()
        if not s.enabled:
            return "Spoken weather is off: turn on speech.enabled (Config > System > Spoken weather)"
        if s.engine == "kokoro":
            return None if s.kokoro_url else "No Kokoro server: set speech.kokoro_url (e.g. http://192.168.0.164:8880)"
        if not s.wyoming_host:
            return "No Piper server: set speech.wyoming_host (e.g. Home Assistant's address)"
        return None

    def audio(self, text: str, force: bool = False) -> bytes:
        """
        `text` read aloud, as a WAV: from the cache, else from the speech server. Raises SpeechError. force: ask the
        server even while it's left alone (a test after restarting it).
        """
        s = self._settings()
        problem = self.problem()
        if problem:
            raise SpeechError(problem, 503)
        if s.engine == "kokoro":
            voice = f"kokoro\n{s.kokoro_url}\n{s.kokoro_voice}\n{s.kokoro_speed}"
        else:
            voice = f"wyoming\n{s.wyoming_host}:{s.wyoming_port}\n{s.wyoming_voice}"
        name = hashlib.sha256(f"{voice}\n{text}".encode()).hexdigest()
        with self._lock:
            if name in self._cache:
                self._cache.move_to_end(name)
                return self._cache[name]
            self._same_server(server_of(s))
            now = self._clock()
            waiting = self._waiting(now)
            if waiting and not force:
                raise SpeechError(waiting, 503)
            render = self._rendering.get(name)
            mine = render is None
            if mine:
                render = self._rendering[name] = _Render(now + s.timeout, s.timeout)
        if not mine:
            return self._wait(render, s)
        try:
            clip = self._render(text, s, render.deadline)
            with self._lock:
                if name not in self._cache:
                    self._cache[name] = clip
                    self._cached += len(clip)
                while self._cached > CACHE_BYTES and len(self._cache) > 1:  # the newest is kept, however big
                    self._cached -= len(self._cache.popitem(last=False)[1])
            render.clip = clip
            return clip
        except SpeechError as e:
            render.error = e
            raise
        finally:  # always, so the next ask makes it again rather than waiting on nothing
            with self._lock:
                self._rendering.pop(name, None)
            render.done.set()

    def _wait(self, render: _Render, s) -> bytes:
        """The clip another ask is making: its clip, or the same error. Waits as long as its time limit allows."""
        if not render.done.wait(max(0.0, render.deadline - self._clock()) + WAIT_GRACE):
            raise timed_out(s, render.timeout)
        if render.clip is None:
            raise SpeechError(str(render.error), render.error.status, render.error.down)
        return render.clip

    def _render(self, text: str, s, deadline: float) -> bytes:
        """Asks the server for a clip, logs how long it took, and keeps how it went (health, backoff)."""
        where = s.kokoro_url if s.engine == "kokoro" else f"{s.wyoming_host}:{s.wyoming_port}"
        server, start = server_of(s), self._clock()
        try:
            clip = self._kokoro(text, s, deadline) if s.engine == "kokoro" else self._synthesize(text, s, deadline)
        except SpeechError as e:
            took = self._clock() - start
            with self._lock:
                # a clip asked for before the wait began (several timing out together) doesn't make it longer
                if self._server == server:
                    self._ok, self._error = False, str(e)
                    if e.down and start >= self._backoff_from:
                        self._backoff = min(MAX_BACKOFF, max(FIRST_BACKOFF, 2 * self._backoff))
                        self._backoff_from = self._clock()
                        self._retry_at = self._backoff_from + self._backoff
                backoff = self._backoff
            then = f"; asking again in {backoff:.0f} s" if e.down else ""
            if e.status == 504:
                said = f"{engine_name(s)} at {where} didn't answer in {s.timeout} s"
                log.error(f"speech: {said} ({len(text)} characters){then}")
            else:
                log.warning(f"speech: {e} ({len(text)} characters, {took:.1f} s){then}")
            raise
        took = self._clock() - start
        with self._lock:
            if self._server == server:
                self._ok, self._error = True, ""
                self._backoff, self._retry_at, self._backoff_from = 0.0, 0.0, -math.inf
        said = f"speech: {engine_name(s)} at {where}, {len(text)} characters, {len(clip) // 1024} KB in {took:.1f} s"
        if took > SLOW_SECONDS:
            log.warning(f"{said} (slow)")
        else:
            log.info(said)
        return clip

    def _synthesize(self, text: str, s, deadline: float) -> bytes:
        """
        Asks the Wyoming server (Home Assistant's Piper) for `text`, and wraps its audio in a WAV. The time limit is
        the socket's timeout, set to what's left of it before each event, checked between them, and _Cutoff's.
        """
        where = f"{s.wyoming_host}:{s.wyoming_port}"
        data = {"text": text}
        if s.wyoming_voice:
            data["voice"] = {"name": s.wyoming_voice}
        try:
            sock = self._connect((s.wyoming_host, s.wyoming_port), timeout=min(CONNECT_SECONDS, s.timeout))
        except OSError as e:  # refused, no route, or no answer in CONNECT_SECONDS
            raise SpeechError(f"Couldn't get speech from {where}: {e}"[:200], down=True) from None

        def left() -> float:
            seconds = deadline - self._clock()
            if seconds <= 0:
                raise timed_out(s)
            return seconds

        cutoff = _Cutoff(sock, deadline - self._clock())
        try:
            with sock, cutoff:
                sock.settimeout(left())
                sock.sendall(wyoming_event("synthesize", data))
                stream = sock.makefile("rb")
                fmt, pcm = None, bytearray()
                while True:
                    sock.settimeout(left())
                    kind, info, payload = read_wyoming_event(stream)
                    if kind == "audio-start":
                        fmt = info
                    elif kind == "audio-chunk":
                        fmt = fmt or info  # each chunk says its format too
                        pcm += payload
                    elif kind == "audio-stop":
                        break
                    elif kind == "error":
                        raise SpeechError(f"Piper at {where}: {info.get('text') or 'error'}"[:200])
        except socket.timeout:
            raise timed_out(s) from None
        except OSError as e:  # the connection broke
            if cutoff.fired:
                raise timed_out(s) from None
            raise SpeechError(f"Couldn't get speech from {where}: {e}"[:200], down=True) from None
        except ValueError as e:  # it answered, with something that isn't Wyoming
            if cutoff.fired:  # or it was cut off at the time limit, mid-event
                raise timed_out(s) from None
            raise SpeechError(f"Couldn't get speech from {where}: {e}"[:200]) from None
        if not fmt or not pcm:
            raise SpeechError(f"Piper at {where} sent no audio")
        return to_wav(pcm, int(fmt["rate"]), int(fmt["width"]), int(fmt["channels"]))

    def _kokoro(self, text: str, s, deadline: float) -> bytes:
        """
        Asks Kokoro-FastAPI for `text` as raw PCM, and wraps it in a WAV. requests' own timeout is per read (a server
        sending a byte at a time never meets it), so the answer is streamed, the time limit checked between chunks,
        and _Cutoff ends a read still going at the time limit.
        """
        url = s.kokoro_url.rstrip("/") + "/v1/audio/speech"
        body = {
            "model": "kokoro",
            "input": text,
            "voice": s.kokoro_voice,
            "speed": s.kokoro_speed,
            "response_format": "pcm",
            "stream": False,
        }
        left = max(0.1, deadline - self._clock())
        try:
            response = self._post(
                url,
                json=body,
                headers={"User-Agent": USER_AGENT},
                timeout=(min(CONNECT_SECONDS, left), left),
                stream=True,
            )
        except requests.ConnectTimeout as e:  # before Timeout: it's both
            raise SpeechError(f"Couldn't reach Kokoro at {s.kokoro_url}: {e}"[:200], down=True) from None
        except requests.Timeout:
            raise timed_out(s) from None
        except requests.ConnectionError as e:  # refused, no route, reset: it's down
            raise SpeechError(f"Couldn't reach Kokoro at {s.kokoro_url}: {e}"[:200], down=True) from None
        except requests.RequestException as e:  # an address it can't use, an answer it can't read: not an outage
            raise SpeechError(f"Couldn't ask Kokoro at {s.kokoro_url}: {e}"[:200]) from None
        cutoff = _Cutoff(_socket_of(response), deadline - self._clock())
        try:
            with cutoff:
                if response.status_code != 200:
                    raise SpeechError(f"Kokoro said {response.status_code}: {_kokoro_detail(response)}"[:200])
                pcm = bytearray()
                for chunk in response.iter_content(CHUNK_BYTES):
                    pcm += chunk
                    if self._clock() > deadline:
                        raise timed_out(s)
                    if len(pcm) > MAX_AUDIO_BYTES:
                        raise SpeechError(f"Kokoro sent too much audio (over {MAX_AUDIO_BYTES // 1024 // 1024} MB)")
            if cutoff.fired:  # an answer without a length just ends when it's cut off
                raise timed_out(s)
        except requests.RequestException as e:
            # a read timeout in the answer comes as a ConnectionError around urllib3's ReadTimeoutError
            timeout = isinstance(e, requests.Timeout) or (e.args and isinstance(e.args[0], ReadTimeoutError))
            if timeout or cutoff.fired:
                raise timed_out(s) from None
            # a reset connection is an outage; a broken chunk or bad encoding is an answer it can't read
            down = isinstance(e, requests.ConnectionError)
            raise SpeechError(f"Kokoro's answer broke off: {e}"[:200], down=down) from None
        finally:
            response.close()
        if len(pcm) < 2:
            raise SpeechError("Kokoro sent no audio")
        if len(pcm) % 2:
            del pcm[-1]  # half a sample
        return to_wav(pcm, KOKORO_RATE, 2, 1)


def _socket_of(response):
    """
    The socket a streamed requests answer is read from, or None (then only the checks between chunks limit it). From
    urllib3's connection; an answer with "Connection: close" has none, so from http.client's file under it.
    """
    raw = getattr(response, "raw", None)
    if raw is None:  # a stand-in in tests
        return None
    sock = getattr(getattr(raw, "connection", None), "sock", None)
    if sock is None:
        fp = getattr(getattr(raw, "_fp", None), "fp", None)  # http.client.HTTPResponse's socket file
        sock = getattr(getattr(fp, "raw", None), "_sock", None)  # BufferedReader > SocketIO > socket
    if sock is None:
        log.debug("speech: no socket to cut Kokoro's answer off at the time limit")
    return sock


def _kokoro_detail(response) -> str:
    """Kokoro's reason ({"detail": {"message": ...}}), cut before its list of every voice."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return (response.text or "").strip()[:150]
    message = str(detail.get("message") or detail) if isinstance(detail, dict) else str(detail)
    return message.split(" Available voices")[0]


# ---- Wyoming --------------------------------------------------------------------------------------------------------
#
# An event is a line of JSON (its type, and the lengths of what follows), then its data as JSON, then its payload
# (audio). A text-to-speech server answers "synthesize" with audio-start, audio-chunk..., audio-stop.


def wyoming_event(kind: str, data: Optional[dict] = None, payload: bytes = b"") -> bytes:
    header = {"type": kind, "version": WYOMING_VERSION}
    body = json.dumps(data).encode() if data else b""
    if body:
        header["data_length"] = len(body)
    if payload:
        header["payload_length"] = len(payload)
    return (json.dumps(header) + "\n").encode() + body + payload


def read_wyoming_event(stream) -> Tuple[str, dict, bytes]:
    """(type, data, payload) of the next event. Raises ValueError if the server closed or sent something else."""
    line = stream.readline(64 * 1024)
    if not line:
        raise ValueError("the server closed the connection")
    header = json.loads(line)  # ValueError if it isn't JSON
    data = header.get("data") or {}  # older servers put it in the header
    lengths = header.get("data_length") or 0, header.get("payload_length") or 0
    if any(not isinstance(n, int) or n < 0 or n > MAX_EVENT_BYTES for n in lengths):
        raise ValueError("an event too big to be audio")
    if lengths[0]:
        data = json.loads(_read_exactly(stream, lengths[0]))
    payload = _read_exactly(stream, lengths[1]) if lengths[1] else b""
    return str(header.get("type")), data, payload


def _read_exactly(stream, n: int) -> bytes:
    data = stream.read(n)
    if len(data) != n:
        raise ValueError("the server closed the connection")
    return data


def to_wav(pcm, rate: int, width: int, channels: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()
