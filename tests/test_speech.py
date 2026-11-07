"""Tests for metarmap.speech: the METARs read aloud by a Piper server (Home Assistant's), faked."""

import io
import json
import socket
import wave
from types import SimpleNamespace

import pytest
import requests

from metarmap import speech as speech_module
from metarmap.settings import SpeechSettings
from metarmap.speech import Speech, SpeechError


class FakeWyoming:
    """Stands in for socket.create_connection: a Wyoming server that answers "synthesize" with `events`."""

    def __init__(self, events=None, fail=None):
        self.sent = []
        self.addresses = []
        self.fail = fail
        self.events = events if events is not None else wyoming_reply(b"\x01\x02" * 800)

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

            def sendall(self, data):
                server.sent.append(data)

            def makefile(self, mode):
                return io.BytesIO(server.events)

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
    assert fake.addresses == [(("192.168.0.14", 10200), speech_module.WYOMING_TIMEOUT)]
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
    monkeypatch.setattr(speech_module, "CACHE_CLIPS", 2)
    speech, fake, _ = make_wyoming()
    for text in ("a", "b", "c"):
        speech.audio(text)
    speech.audio("c")  # still kept
    speech.audio("a")  # dropped: asked again
    assert [sent_events_of(data)[1]["text"] for data in fake.sent] == ["a", "b", "c", "a"]


def sent_events_of(data):
    kind, info, _ = speech_module.read_wyoming_event(io.BytesIO(data))
    return kind, info


# ---- Kokoro (Kokoro-FastAPI) ---------------------------------------------------------------------------------------


class FakeKokoro:
    """Stands in for requests.post: records each request and answers with raw PCM, or what it's told to."""

    def __init__(self, status=200, content=b"\x01\x02" * 1200, body=None, fail=None):
        self.calls = []
        self.status, self.content, self.body, self.fail = status, content, body, fail

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append(SimpleNamespace(url=url, json=json, headers=headers, timeout=timeout))
        if self.fail:
            raise self.fail
        body = self.body

        def as_json():
            if body is None:
                raise ValueError("not JSON")
            return body

        return SimpleNamespace(status_code=self.status, content=self.content, text=str(body or ""), json=as_json)


def make_kokoro(fake=None, **settings):
    fake = fake or FakeKokoro()
    s = SpeechSettings(enabled=True, engine="kokoro", kokoro_url="http://192.168.0.164:8880", **settings)
    return Speech(lambda: s, post=fake), fake, s


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
    assert call.timeout
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
