"""Tests for metarmap.speech: the METARs read aloud by a Piper server (Home Assistant's), faked."""

import io
import json
import socket
import wave

import pytest

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
    s = SpeechSettings(wyoming_host="192.168.0.14", **settings)
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
