"""
The spoken METARs (metarmap.spoken) as audio: /api/speak/<code>.audio. The words are read by a speech server on
another computer (speech.engine), so the Pi only sends the text and keeps the audio it gets back, as a WAV (16-bit
mono): it suits a Pi Zero W, which couldn't make speech itself.

  wyoming  Piper, over the Wyoming protocol: Home Assistant's Piper add-on, or any wyoming-piper server
           (speech.wyoming_host, port 10200). 16 or 22 kHz, by the voice
  kokoro   Kokoro-FastAPI (speech.kokoro_url, e.g. http://192.168.0.164:8880), over its OpenAI-style speech API:
           asked for raw PCM (24 kHz) and wrapped in a WAV here, as its own WAVs are written for streaming

Each clip is kept until its text changes (a new METAR), so playing an airport again takes no time.
"""

import hashlib
import io
import json
import logging
import socket
import threading
import wave
from collections import OrderedDict
from typing import Callable, Optional, Tuple

import requests

from metarmap import USER_AGENT

log = logging.getLogger(__name__)

CACHE_CLIPS = 60  # a clip is about 500 KB (15 s at 16-22 kHz): 30 MB at most, kept in memory
WYOMING_TIMEOUT = 60  # seconds for the whole report: Home Assistant's box may be busy
WYOMING_VERSION = "1.5.0"  # the protocol version the map speaks (wyoming 1.5 and later understand it)
MAX_EVENT_BYTES = 4 * 1024 * 1024  # an audio chunk is a few KB; anything this big isn't a Wyoming server
KOKORO_RATE = 24000  # Kokoro's raw PCM: 16-bit mono at 24 kHz
KOKORO_TIMEOUT = 60


def configured(s) -> bool:
    """Whether speech is on, with a server named for its engine (the AWOS buttons and tab show then)."""
    return s.enabled and bool(s.kokoro_url if s.engine == "kokoro" else s.wyoming_host)


class SpeechError(Exception):
    """Why there's no audio. status: the HTTP status the API should answer with."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class Speech:
    """
    settings: returns the speech settings now (settings.SpeechSettings), so a change applies at once.
    connect: socket.create_connection, or a stand-in in tests.
    """

    def __init__(self, settings: Callable, connect=None, post=None):
        self._settings = settings
        self._connect = connect or socket.create_connection
        self._post = post or requests.post
        self._lock = threading.Lock()
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()

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

    def audio(self, text: str) -> bytes:
        """`text` read aloud, as a WAV: from the cache, else from the Piper server. Raises SpeechError."""
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
        clip = self._kokoro(text, s) if s.engine == "kokoro" else self._synthesize(text, s)
        with self._lock:
            self._cache[name] = clip
            while len(self._cache) > CACHE_CLIPS:
                self._cache.popitem(last=False)
        return clip

    def _synthesize(self, text: str, s) -> bytes:
        """Asks the Wyoming server (Home Assistant's Piper) for `text`, and wraps its audio in a WAV."""
        where = f"{s.wyoming_host}:{s.wyoming_port}"
        data = {"text": text}
        if s.wyoming_voice:
            data["voice"] = {"name": s.wyoming_voice}
        try:
            with self._connect((s.wyoming_host, s.wyoming_port), timeout=WYOMING_TIMEOUT) as sock:
                sock.sendall(wyoming_event("synthesize", data))
                stream = sock.makefile("rb")
                fmt, pcm = None, bytearray()
                while True:
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
        except (OSError, ValueError) as e:
            raise SpeechError(f"Couldn't get speech from {where}: {e}"[:200]) from None
        if not fmt or not pcm:
            raise SpeechError(f"Piper at {where} sent no audio")
        log.info(f"speech: {where}, {len(text)} characters, {len(pcm) // 1024} KB")
        return to_wav(bytes(pcm), int(fmt["rate"]), int(fmt["width"]), int(fmt["channels"]))

    def _kokoro(self, text: str, s) -> bytes:
        """Asks Kokoro-FastAPI for `text` as raw PCM, and wraps it in a WAV."""
        url = s.kokoro_url.rstrip("/") + "/v1/audio/speech"
        body = {
            "model": "kokoro",
            "input": text,
            "voice": s.kokoro_voice,
            "speed": s.kokoro_speed,
            "response_format": "pcm",
            "stream": False,
        }
        try:
            response = self._post(url, json=body, headers={"User-Agent": USER_AGENT}, timeout=KOKORO_TIMEOUT)
        except requests.RequestException as e:
            raise SpeechError(f"Couldn't reach Kokoro at {s.kokoro_url}: {e}"[:200]) from None
        if response.status_code != 200:
            raise SpeechError(f"Kokoro said {response.status_code}: {_kokoro_detail(response)}"[:200])
        pcm = response.content
        if len(pcm) < 2:
            raise SpeechError("Kokoro sent no audio")
        log.info(f"speech: kokoro {s.kokoro_url}, {len(text)} characters, {len(pcm) // 1024} KB")
        return to_wav(pcm[: len(pcm) // 2 * 2], KOKORO_RATE, 2, 1)


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


def to_wav(pcm: bytes, rate: int, width: int, channels: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()
