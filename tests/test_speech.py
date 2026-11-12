"""Tests for metarmap.speech: the METARs read aloud by a Piper server (Home Assistant's), faked."""

import io
import json
import logging
import socket
import threading
import time
import wave
from types import SimpleNamespace

import pytest
import requests

from metarmap import speech as speech_module
from metarmap.settings import SpeechSettings
from metarmap.speech import Speech, SpeechError


class FakeWyoming:
    """Stands in for socket.create_connection: a Wyoming server that answers "synthesize" with `events`."""

    def __init__(self, events=None, fail=None, stream=None):
        self.sent = []
        self.addresses = []
        self.timeouts = []  # each settimeout()
        self.fail = fail
        self.events = events if events is not None else wyoming_reply(b"\x01\x02" * 800)
        self.stream = stream  # what makefile() gives, instead of the events

    def __call__(self, address, timeout=None):
        self.addresses.append((address, timeout))
        if self.fail:
            raise self.fail
        server = self

        class Socket:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def settimeout(self, seconds):
                server.timeouts.append(seconds)

            def sendall(self, data):
                server.sent.append(data)

            def makefile(self, mode):
                return server.stream or io.BytesIO(server.events)

        return Socket()


def wyoming_reply(pcm, rate=16000, chunks=2, inline=False):
    """What a Wyoming Piper server sends: audio-start, the audio in chunks, audio-stop."""
    fmt = {"rate": rate, "width": 2, "channels": 1}
    if inline:  # an older server: the data in the header line
        line = {"type": "audio-start", "data": fmt}
        out = (json.dumps(line) + "\n").encode()
    else:
        out = speech_module.wyoming_event("audio-start", fmt)
    size = len(pcm) // chunks
    for i in range(chunks):
        part = pcm[i * size : (i + 1) * size if i < chunks - 1 else None]
        out += speech_module.wyoming_event("audio-chunk", fmt, part)
    return out + speech_module.wyoming_event("audio-stop")


def make_wyoming(fake=None, **settings):
    fake = fake or FakeWyoming()
    settings.setdefault("timeout", 30)  # short, as the tests' numbers are (the default is 120)
    s = SpeechSettings(enabled=True, wyoming_host="192.168.0.14", **settings)
    return Speech(lambda: s, connect=fake), fake, s


def sent_events(fake):
    """The events the map sent, as (type, data)."""
    stream = io.BytesIO(b"".join(fake.sent))
    kind, data, _ = speech_module.read_wyoming_event(stream)
    return [(kind, data)]


def test_wyoming_asks_for_the_text_and_makes_a_wav():
    pcm = bytes(range(256)) * 10
    speech, fake, _ = make_wyoming(FakeWyoming(wyoming_reply(pcm, chunks=3)))
    clip = speech.audio("Hooks. Wind calm.")
    assert fake.addresses == [(("192.168.0.14", 10200), speech_module.CONNECT_SECONDS)]
    assert fake.timeouts and all(0 < t <= 30 for t in fake.timeouts)  # what's left of speech.timeout
    assert sent_events(fake) == [("synthesize", {"text": "Hooks. Wind calm."})]  # the server's own voice
    with wave.open(io.BytesIO(clip)) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (16000, 2, 1)
        assert w.readframes(w.getnframes()) == pcm  # every chunk, in order


def test_wyoming_voice_and_port():
    speech, fake, _ = make_wyoming(wyoming_port=10201, wyoming_voice="en_US-lessac-medium")
    speech.audio("Hooks.")
    assert fake.addresses[0][0] == ("192.168.0.14", 10201)
    assert sent_events(fake) == [("synthesize", {"text": "Hooks.", "voice": {"name": "en_US-lessac-medium"}})]


def test_an_older_wyoming_server():
    """Data in the header line, as servers before wyoming 1.5 sent it."""
    speech, _, _ = make_wyoming(FakeWyoming(wyoming_reply(b"\x00\x01" * 100, rate=22050, inline=True)))
    clip = speech.audio("Hooks.")
    with wave.open(io.BytesIO(clip)) as w:
        assert w.getframerate() == 22050


def test_wyoming_clips_are_kept():
    speech, fake, s = make_wyoming()
    speech.audio("one")
    speech.audio("one")
    assert len(fake.sent) == 1
    s.wyoming_voice = "en_US-amy-low"
    speech.audio("one")  # another voice: another clip
    assert len(fake.sent) == 2


def test_no_wyoming_host():
    speech, fake, s = make_wyoming()
    s.wyoming_host = ""
    assert "speech.wyoming_host" in speech.problem()
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 503 and fake.addresses == []


@pytest.mark.parametrize(
    "fake, said",
    [
        (FakeWyoming(fail=ConnectionRefusedError("Connection refused")), "Couldn't get speech from 192.168.0.14:10200"),
        (FakeWyoming(fail=socket.timeout("timed out")), "timed out"),
        (FakeWyoming(speech_module.wyoming_event("error", {"text": "no voice named x"})), "no voice named x"),
        (FakeWyoming(b""), "closed the connection"),
        (FakeWyoming(b"HTTP/1.1 400 Bad Request\r\n\r\n"), "Couldn't get speech"),  # not a Wyoming server
        (FakeWyoming(speech_module.wyoming_event("audio-stop")), "sent no audio"),
        (FakeWyoming(b'{"type": "audio-chunk", "payload_length": 999999999}\n'), "too big"),
    ],
)
def test_wyoming_failures_say_why(fake, said):
    speech, _, _ = make_wyoming(fake)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert said in str(e.value) and e.value.status == 502


def test_the_cache_keeps_the_newest(monkeypatch):
    clip = len(make_wyoming()[0].audio("a"))  # the fake's clips are all this long
    monkeypatch.setattr(speech_module, "CACHE_BYTES", 2 * clip)  # room for two
    speech, fake, _ = make_wyoming()
    for text in ("a", "b", "c"):
        speech.audio(text)
    speech.audio("c")  # still kept
    speech.audio("a")  # dropped: asked again
    assert [sent_events_of(data)[1]["text"] for data in fake.sent] == ["a", "b", "c", "a"]


def test_a_clip_bigger_than_the_cache_is_still_kept(monkeypatch):
    """An ATIS can be a few MB: the newest clip stays, so playing it again (Safari's ranges) doesn't ask again."""
    monkeypatch.setattr(speech_module, "CACHE_BYTES", 10)
    speech, fake, _ = make_wyoming()
    speech.audio("a long ATIS")
    speech.audio("a long ATIS")
    assert len(fake.sent) == 1


def sent_events_of(data):
    kind, info, _ = speech_module.read_wyoming_event(io.BytesIO(data))
    return kind, info


# ---- Kokoro (Kokoro-FastAPI) ---------------------------------------------------------------------------------------


class FakeKokoro:
    """
    Stands in for requests.post: records each request and answers with raw PCM, or what it's told to.
    chunks: the answer's pieces as iter_content gives them (else `content` in one); each one runs `between` first.
    """

    def __init__(self, status=200, content=b"\x01\x02" * 1200, body=None, fail=None, chunks=None, between=None):
        self.calls = []
        self.status, self.content, self.body, self.fail = status, content, body, fail
        self.chunks, self.between = chunks, between
        self.closed = 0

    def __call__(self, url, json=None, headers=None, timeout=None, stream=False):
        self.calls.append(SimpleNamespace(url=url, json=json, headers=headers, timeout=timeout, stream=stream))
        fail = self.fail() if callable(self.fail) else self.fail
        if fail:
            raise fail
        body, fake = self.body, self

        def as_json():
            if body is None:
                raise ValueError("not JSON")
            return body

        def iter_content(size):
            for chunk in fake.chunks if fake.chunks is not None else [fake.content]:
                if fake.between:
                    fake.between()
                yield chunk

        def close():
            fake.closed += 1

        return SimpleNamespace(
            status_code=self.status, text=str(body or ""), json=as_json, iter_content=iter_content, close=close
        )


def make_kokoro(fake=None, clock=None, **settings):
    fake = fake or FakeKokoro()
    settings.setdefault("timeout", 30)  # short, as the tests' numbers are (the default is 120)
    s = SpeechSettings(enabled=True, engine="kokoro", kokoro_url="http://192.168.0.164:8880", **settings)
    return Speech(lambda: s, post=fake, clock=clock), fake, s


def test_kokoro_asks_for_raw_audio_and_makes_a_wav():
    pcm = bytes(range(256)) * 10
    speech, fake, _ = make_kokoro(FakeKokoro(content=pcm))
    clip = speech.audio("Hooks. Wind calm.")
    (call,) = fake.calls
    assert call.url == "http://192.168.0.164:8880/v1/audio/speech"
    assert call.json == {
        "model": "kokoro",
        "input": "Hooks. Wind calm.",
        "voice": "af_heart",
        "speed": 1.0,
        "response_format": "pcm",
        "stream": False,
    }
    connect, read = call.timeout
    assert connect == speech_module.CONNECT_SECONDS and 29 < read <= 30  # what's left of speech.timeout
    assert call.stream  # read in chunks, to check the time limit between them
    assert fake.closed == 1
    with wave.open(io.BytesIO(clip)) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (24000, 2, 1)
        assert w.readframes(w.getnframes()) == pcm


def test_kokoro_voice_and_speed_make_new_clips():
    speech, fake, s = make_kokoro()
    speech.audio("one")
    speech.audio("one")
    assert len(fake.calls) == 1
    s.kokoro_voice = "bm_george"
    speech.audio("one")
    s.kokoro_speed = 1.25
    speech.audio("one")
    assert [(c.json["voice"], c.json["speed"]) for c in fake.calls] == [
        ("af_heart", 1.0),
        ("bm_george", 1.0),
        ("bm_george", 1.25),
    ]


def test_a_new_engine_is_a_new_clip():
    speech, fake, s = make_kokoro()
    speech.audio("one")
    s.engine, s.wyoming_host = "wyoming", "192.168.0.14"
    wyoming = FakeWyoming()
    speech._connect = wyoming
    speech.audio("one")
    assert len(fake.calls) == 1 and len(wyoming.sent) == 1


def test_an_odd_byte_is_dropped():
    speech, _, _ = make_kokoro(FakeKokoro(content=b"\x01\x02\x03"))
    with wave.open(io.BytesIO(speech.audio("one"))) as w:
        assert w.getnframes() == 1


def test_no_kokoro_server():
    speech, fake, s = make_kokoro()
    s.kokoro_url = ""
    assert "speech.kokoro_url" in speech.problem()
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 503 and fake.calls == []


@pytest.mark.parametrize(
    "fake, said",
    [
        (
            FakeKokoro(
                status=400,
                body={"detail": {"message": "Voice 'xx_nope' not found. Available voices: af_alloy, af_bella"}},
            ),
            "Kokoro said 400: Voice 'xx_nope' not found.",
        ),
        (FakeKokoro(status=500, body=None), "Kokoro said 500"),
        (FakeKokoro(content=b""), "sent no audio"),
        (FakeKokoro(fail=requests.ConnectionError("refused")), "Couldn't reach Kokoro at http://192.168.0.164:8880"),
    ],
)
def test_kokoro_failures_say_why(fake, said):
    speech, _, _ = make_kokoro(fake)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert said in str(e.value) and e.value.status == 502
    assert "af_bella" not in str(e.value)  # not its whole voice list


def test_configured():
    on = dict(enabled=True)
    assert not speech_module.configured(SpeechSettings(**on))
    assert speech_module.configured(SpeechSettings(wyoming_host="192.168.0.14", **on))
    assert not speech_module.configured(SpeechSettings(engine="kokoro", wyoming_host="192.168.0.14", **on))
    assert speech_module.configured(SpeechSettings(engine="kokoro", kokoro_url="http://192.168.0.164:8880", **on))
    assert not speech_module.configured(SpeechSettings(wyoming_host="192.168.0.14"))  # off: a server isn't enough


def test_speech_off():
    """Off, the map doesn't ask the server at all, and says how to turn it on."""
    speech, fake, s = make_wyoming()
    s.enabled = False
    assert "speech.enabled" in speech.problem()
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 503 and fake.addresses == []


# ---- a slow or hung server: the time limit, the backoff, one clip made at a time, the health -------------------------


class Clock:
    """A clock the test moves: Speech's clock."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_time_limit_is_two_minutes_unless_set():
    """A Kokoro without a GPU reads slower than real time: an AWOS can take 30 s, so the default leaves room."""
    assert SpeechSettings().timeout == 120


def test_kokoro_not_answering_in_time_is_a_504():
    clock = Clock()
    speech, fake, _ = make_kokoro(FakeKokoro(fail=requests.ReadTimeout("read timed out")), clock=clock)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Kokoro didn't answer in 30 s")
    assert speech.health() == (False, "The speech server isn't answering; trying again in 30 s")


def test_a_trickling_kokoro_is_cut_off_at_the_time_limit():
    """A byte now and then never meets requests' own (per read) timeout: the map's time limit stops it."""
    clock = Clock()

    def tick():
        clock.now += 10

    fake = FakeKokoro(chunks=[b"\x01\x02"] * 100, between=tick)
    speech, _, _ = make_kokoro(fake, clock=clock, timeout=30)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 504 and fake.closed == 1
    assert clock.now - 1000 <= 40  # stopped at the first chunk past 30 s, not after all 100


def test_kokoro_breaking_off_on_a_read_timeout_is_a_504():
    """requests gives a read timeout in the answer as a ConnectionError around urllib3's ReadTimeoutError."""
    from urllib3.exceptions import ReadTimeoutError

    def broken():
        raise requests.ConnectionError(ReadTimeoutError(None, "/v1/audio/speech", "Read timed out."))
        yield b""

    fake = FakeKokoro()
    speech, _, _ = make_kokoro(fake, timeout=15)

    def post(*args, **kwargs):
        response = fake(*args, **kwargs)
        response.iter_content = lambda size: broken()
        return response

    speech._post = post
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Kokoro didn't answer in 15 s")


def test_after_no_answer_the_map_answers_503_at_once_and_backs_off():
    clock = Clock()
    fake = FakeKokoro(fail=requests.ConnectionError("refused"))
    speech, _, _ = make_kokoro(fake, clock=clock)
    with pytest.raises(SpeechError):
        speech.audio("Hooks.")
    clock.now += 10
    with pytest.raises(SpeechError) as e:
        speech.audio("Another airport.")  # any text: it's the server that isn't answering
    assert (e.value.status, str(e.value)) == (503, "The speech server isn't answering; trying again in 20 s")
    assert len(fake.calls) == 1  # not asked
    assert speech.health() == (False, "The speech server isn't answering; trying again in 20 s")
    # each time it still doesn't answer, it's left alone longer: 30 s, 1, 2, 4 and then 5 minutes
    waits = []
    for _ in range(6):
        clock.now = speech._retry_at
        with pytest.raises(SpeechError) as e:
            speech.audio("Hooks.")
        assert e.value.status == 502
        waits.append(speech._retry_at - clock.now)
    assert waits == [60, 120, 240, 300, 300, 300]
    assert len(fake.calls) == 7


def test_a_clip_made_ends_the_backoff():
    clock = Clock()
    fake = FakeKokoro(fail=requests.ReadTimeout("read timed out"))
    speech, _, _ = make_kokoro(fake, clock=clock)
    for _ in range(3):  # 30, 60, 120 s
        clock.now = speech._retry_at
        with pytest.raises(SpeechError):
            speech.audio("Hooks.")
    clock.now = speech._retry_at
    fake.fail = None
    speech.audio("Hooks.")
    assert speech.health() == (True, "")
    fake.fail = requests.ReadTimeout("read timed out")
    with pytest.raises(SpeechError):
        speech.audio("Another.")
    assert speech._retry_at - clock.now == 30  # from the start again


@pytest.mark.parametrize(
    "change",
    [
        {"kokoro_url": "http://192.168.0.165:8880"},
        {"kokoro_voice": "bm_george"},
        {"kokoro_speed": 1.25},
        {"timeout": 60},
        {"engine": "wyoming", "wyoming_host": "192.168.0.14"},
    ],
)
def test_another_server_or_voice_ends_the_backoff(change):
    clock = Clock()
    fake = FakeKokoro(fail=requests.ConnectionError("refused"))
    speech, _, s = make_kokoro(fake, clock=clock)
    speech._connect = FakeWyoming()
    with pytest.raises(SpeechError):
        speech.audio("Hooks.")
    for key, value in change.items():
        setattr(s, key, value)
    assert speech.health() == (None, "")  # nothing made with these settings yet
    fake.fail = None
    speech.audio("Hooks.")  # asked at once
    assert speech.health() == (True, "")


def test_a_clip_already_made_plays_during_the_backoff():
    clock = Clock()
    fake = FakeKokoro()
    speech, _, _ = make_kokoro(fake, clock=clock)
    clip = speech.audio("Hooks.")
    fake.fail = requests.ConnectionError("refused")
    with pytest.raises(SpeechError):
        speech.audio("Another.")
    assert speech.audio("Hooks.") == clip
    with pytest.raises(SpeechError) as e:
        speech.audio("Another.")
    assert e.value.status == 503 and len(fake.calls) == 2


def test_a_wyoming_server_not_answering_in_time():
    """The time limit is checked between events, and is the socket's timeout for each read."""
    clock = Clock()

    class Slow(io.BytesIO):
        def readline(self, *args):
            clock.now += 20  # each event takes 20 s
            return super().readline(*args)

    fake = FakeWyoming(stream=Slow(wyoming_reply(b"\x01\x02" * 800, chunks=10)))
    s = SpeechSettings(enabled=True, wyoming_host="192.168.0.14", timeout=30)
    speech = Speech(lambda: s, connect=fake, clock=clock)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Piper didn't answer in 30 s")
    assert fake.timeouts == [30, 30, 10]  # sending, the first event, the second (what's left)


def test_a_wyoming_read_timing_out_is_a_504():
    class Hung(io.BytesIO):
        def readline(self, *args):
            raise socket.timeout("timed out")

    speech, _, _ = make_wyoming(FakeWyoming(stream=Hung()))
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Piper didn't answer in 30 s")
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 503  # backed off


class Blocking(FakeKokoro):
    """A Kokoro that holds each request until the test lets it go (`go`), then answers or fails."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.entered, self.go = threading.Event(), threading.Event()

    def __call__(self, *args, **kwargs):
        self.entered.set()
        assert self.go.wait(5)
        return super().__call__(*args, **kwargs)


def ask_in_a_thread(speech, text, results):
    def run():
        try:
            results.append(speech.audio(text))
        except SpeechError as e:
            results.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def waiting(speech):
    """An Event set once a second ask is waiting on the first's clip."""
    event, wait = threading.Event(), speech._wait

    def instrumented(*args):
        event.set()
        return wait(*args)

    speech._wait = instrumented
    return event


def test_two_asks_for_the_same_clip_make_one():
    fake = Blocking()
    speech, _, _ = make_kokoro(fake)
    first, second = [], []
    a = ask_in_a_thread(speech, "Hooks.", first)
    assert fake.entered.wait(5)
    b_waits = waiting(speech)
    b = ask_in_a_thread(speech, "Hooks.", second)
    assert b_waits.wait(5)  # on a's clip
    assert second == [] and len(fake.calls) == 0
    fake.go.set()
    a.join(5)
    b.join(5)
    assert len(fake.calls) == 1
    assert first[0] == second[0] and isinstance(first[0], bytes)
    assert speech._rendering == {}


def test_the_second_ask_gets_the_firsts_error():
    fake = Blocking(status=400, body={"detail": {"message": "Voice 'xx' not found."}})
    speech, _, _ = make_kokoro(fake)
    first, second = [], []
    a = ask_in_a_thread(speech, "Hooks.", first)
    assert fake.entered.wait(5)
    b_waits = waiting(speech)
    b = ask_in_a_thread(speech, "Hooks.", second)
    assert b_waits.wait(5)
    fake.go.set()
    a.join(5)
    b.join(5)
    assert len(fake.calls) == 1
    assert [(e.status, str(e)) for e in first + second] == [(502, "Kokoro said 400: Voice 'xx' not found.")] * 2


def test_a_second_ask_waits_no_longer_than_the_time_limit(monkeypatch):
    monkeypatch.setattr(speech_module, "WAIT_GRACE", 0.0)
    clock = Clock()
    fake = Blocking()
    speech, _, _ = make_kokoro(fake, clock=clock, timeout=20)
    first = []
    a = ask_in_a_thread(speech, "Hooks.", first)
    assert fake.entered.wait(5)
    clock.now += 21  # past the first's time limit
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Kokoro didn't answer in 20 s")
    fake.go.set()
    a.join(5)
    assert speech._rendering == {}


def test_a_clip_failing_unexpectedly_is_asked_again_next_time():
    fake = FakeKokoro(fail=RuntimeError("a bug"))
    speech, _, _ = make_kokoro(fake)
    with pytest.raises(RuntimeError):
        speech.audio("Hooks.")
    assert speech._rendering == {}  # nothing left waiting on it
    fake.fail = None
    assert speech.audio("Hooks.").startswith(b"RIFF")
    assert len(fake.calls) == 2


def test_the_health_before_and_after():
    fake = FakeKokoro()
    speech, _, _ = make_kokoro(fake)
    assert speech.health() == (None, "")  # nothing made yet
    speech.audio("Hooks.")
    assert speech.health() == (True, "")
    fake.status, fake.body = 500, {"detail": "boom"}
    with pytest.raises(SpeechError):
        speech.audio("Another.")
    assert speech.health() == (False, "Kokoro said 500: boom")
    assert speech._retry_at == 0  # it answered: no backoff


def test_each_clip_is_logged_with_how_long_it_took(caplog):
    clock = Clock()
    took = [2]

    def tick():
        clock.now += took[0]

    speech, fake, _ = make_kokoro(FakeKokoro(between=tick), clock=clock)
    with caplog.at_level(logging.INFO, logger="metarmap.speech"):
        speech.audio("Hooks. Wind calm.")
        took[0] = 12
        speech.audio("Hooks. Wind calm, again.")
        fake.fail = requests.ReadTimeout("read timed out")
        with pytest.raises(SpeechError):
            speech.audio("Hooks. Secret words.")
    levels = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert levels[0][0] == logging.INFO and "17 characters" in levels[0][1] and "in 2.0 s" in levels[0][1]
    assert levels[1][0] == logging.WARNING and "in 12.0 s (slow)" in levels[1][1]
    assert levels[2][0] == logging.ERROR and "didn't answer in 30 s (20 characters)" in levels[2][1]
    assert "Secret" not in caplog.text  # the length, not the text


class CutSocket:
    """A socket whose reads block until the map shuts it down (its _Cutoff, at the time limit)."""

    def __init__(self):
        self.shut = threading.Event()

    def shutdown(self, how):
        self.shut.set()


def test_kokoro_is_cut_off_mid_read_at_the_time_limit():
    """A read that's still going (urllib3 filling a chunk, a byte at a time) is ended by shutting the socket down."""
    clock, sock = Clock(), CutSocket()
    fake = FakeKokoro()

    def post(*args, **kwargs):
        response = fake(*args, **kwargs)
        clock.now += 29.95  # the answer starts just before the time limit...
        response.raw = SimpleNamespace(connection=SimpleNamespace(sock=sock))

        def blocked(size):
            assert sock.shut.wait(5)  # ...and its first read only ends when the map cuts it off
            raise requests.ConnectionError("Connection broken: IncompleteRead")
            yield b""

        response.iter_content = blocked
        return response

    speech, _, _ = make_kokoro(fake, clock=clock)
    speech._post = post
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Kokoro didn't answer in 30 s")


def test_wyoming_is_cut_off_mid_read_at_the_time_limit():
    clock, sock = Clock(), CutSocket()

    class Blocked(io.BytesIO):
        def readline(self, *args):
            assert sock.shut.wait(5)
            return b""  # the server's end, as a shut-down socket reads

    fake = FakeWyoming(stream=Blocked())

    def connect(address, timeout=None):
        socket_ = fake(address, timeout)
        socket_.shutdown = sock.shutdown
        clock.now += 29.95
        return socket_

    s = SpeechSettings(enabled=True, wyoming_host="192.168.0.14", timeout=30)
    speech = Speech(lambda: s, connect=connect, clock=clock)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert (e.value.status, str(e.value)) == (504, "Piper didn't answer in 30 s")


def test_the_health_says_the_wait_while_the_server_is_left_alone():
    clock = Clock()
    speech, _, _ = make_kokoro(FakeKokoro(fail=requests.ReadTimeout("read timed out")), clock=clock)
    with pytest.raises(SpeechError):
        speech.audio("Hooks.")
    clock.now += 10
    assert speech.health() == (False, "The speech server isn't answering; trying again in 20 s")  # as the 503 says
    clock.now += 20
    assert speech.health() == (False, "Kokoro didn't answer in 30 s")  # the wait over: the last failure


def test_force_asks_the_server_during_the_backoff():
    """Config's Test and the Pronunciation speaker: to try a server just restarted."""
    clock = Clock()
    fake = FakeKokoro(fail=requests.ConnectionError("refused"))
    speech, _, _ = make_kokoro(fake, clock=clock)
    with pytest.raises(SpeechError):
        speech.audio("Hooks.")
    fake.fail = None  # restarted
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 503 and len(fake.calls) == 1
    assert speech.audio("Hooks.", force=True).startswith(b"RIFF")
    assert len(fake.calls) == 2 and speech.health() == (True, "")
    speech.audio("Another.")  # and the wait is over for everyone


def test_clips_failing_together_lengthen_the_wait_once():
    """Three clips asked at once, all timing out: one wait of 30 s, not 30, 60 and 120."""
    clock = Clock()

    class Together(FakeKokoro):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.count, self.all_in, self.go = 0, threading.Event(), threading.Event()
            self.counting = threading.Lock()

        def __call__(self, *args, **kwargs):
            with self.counting:
                self.count += 1
                if self.count == 3:
                    self.all_in.set()
            assert self.go.wait(5)
            return super().__call__(*args, **kwargs)

    fake = Together(fail=requests.ReadTimeout("read timed out"))
    speech, _, _ = make_kokoro(fake, clock=clock)
    results = []
    threads = [ask_in_a_thread(speech, text, results) for text in ("KHOU.", "KIAH.", "KGLS.")]
    assert fake.all_in.wait(5)
    clock.now += 30
    fake.go.set()
    for thread in threads:
        thread.join(5)
    assert [e.status for e in results] == [504, 504, 504]
    assert speech._retry_at - clock.now == 30
    clock.now = speech._retry_at  # the next one asked after the wait, failing, does lengthen it
    with pytest.raises(SpeechError):
        speech.audio("KHOU.")
    assert speech._retry_at - clock.now == 60


@pytest.mark.parametrize(
    "where, fail, down",
    [
        ("post", requests.ConnectionError("refused"), True),
        ("post", requests.exceptions.InvalidURL("bad"), False),
        ("body", requests.ConnectionError("Connection reset by peer"), True),
        ("body", requests.exceptions.ChunkedEncodingError("broken chunk"), False),
        ("body", requests.exceptions.ContentDecodingError("bad gzip"), False),
    ],
)
def test_only_an_outage_starts_the_backoff(where, fail, down):
    """A server that answered, badly, is asked again next time: no wait."""
    fake = FakeKokoro(fail=fail if where == "post" else None)
    speech, _, _ = make_kokoro(fake)
    if where == "body":

        def broken(size):
            raise fail
            yield b""

        post = fake

        def fake_post(*args, **kwargs):
            response = post(*args, **kwargs)
            response.iter_content = broken
            return response

        speech._post = fake_post
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 502 and e.value.down is down
    assert (speech._retry_at > 0) is down


def test_too_much_audio_is_refused(monkeypatch):
    monkeypatch.setattr(speech_module, "MAX_AUDIO_BYTES", 100)
    fake = FakeKokoro(chunks=[b"\x01\x02" * 40] * 5)
    speech, _, _ = make_kokoro(fake)
    with pytest.raises(SpeechError) as e:
        speech.audio("Hooks.")
    assert e.value.status == 502 and "sent too much audio" in str(e.value)
    assert speech._retry_at == 0 and fake.closed == 1


def test_the_socket_of_an_answer_with_connection_close():
    """urllib3's connection has no socket then: it's found in http.client's file under it."""
    sock = object()
    file = SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(_sock=sock)))
    raw = SimpleNamespace(connection=SimpleNamespace(sock=None), _fp=file)
    assert speech_module._socket_of(SimpleNamespace(raw=raw)) is sock
    direct = SimpleNamespace(raw=SimpleNamespace(connection=SimpleNamespace(sock=sock)))
    assert speech_module._socket_of(direct) is sock


def test_no_socket_found_is_logged(caplog):
    with caplog.at_level(logging.DEBUG, logger="metarmap.speech"):
        assert speech_module._socket_of(SimpleNamespace(raw=SimpleNamespace(connection=None))) is None
    assert "no socket" in caplog.text


def test_a_real_trickling_server_with_connection_close_is_cut_off():
    """A real socket: an answer with no length and "Connection: close", two bytes at a time."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    stop = threading.Event()

    def trickle():
        conn, _ = server.accept()
        with conn:
            conn.recv(65536)
            try:
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: audio/pcm\r\nConnection: close\r\n\r\n")
                while not stop.wait(0.05):
                    conn.sendall(b"\x01\x02")
            except OSError:  # the map shut it down
                pass

    threading.Thread(target=trickle, daemon=True).start()
    shift = [0.0]  # the clock jumps once the answer starts, so the time limit comes in a fraction of a second

    def post(*args, **kwargs):
        response = requests.post(*args, **kwargs)
        shift[0] = 4.7
        return response

    s = SpeechSettings(enabled=True, engine="kokoro", kokoro_url=f"http://127.0.0.1:{server.getsockname()[1]}")
    s.timeout = 5
    speech = Speech(lambda: s, post=post, clock=lambda: time.monotonic() + shift[0])
    started = time.monotonic()
    try:
        with pytest.raises(SpeechError) as e:
            speech.audio("Hooks.")
    finally:
        stop.set()
        server.close()
    assert (e.value.status, str(e.value)) == (504, "Kokoro didn't answer in 5 s")
    assert time.monotonic() - started < 3
