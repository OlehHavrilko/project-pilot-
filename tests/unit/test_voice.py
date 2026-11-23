"""Unit tests for the local voice subsystem (no piper model needed)."""

from __future__ import annotations

import base64
import threading
import time

from voice.cache import PcmCache
from voice.piper_backend import PiperBackend
from voice.speaker import Speaker
from voice.tts import AudioChunk


class FakeBackend:
    name = "fake:voice"

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.release = threading.Event()
        self.block = False

    def stream(self, text: str):
        self.texts.append(text)
        if self.block:
            self.release.wait(5)
        yield AudioChunk(pcm=b"\x01\x00" * 10, sample_rate=22050)
        yield AudioChunk(pcm=b"\x02\x00" * 10, sample_rate=22050)


class FakeBridge:
    def __init__(self) -> None:
        self.plays: list[tuple[int, int, int]] = []
        self._lock = threading.Lock()

    def play(self, pcm_base64: str, sample_rate: int = 24000, channels: int = 1) -> dict:
        with self._lock:
            self.plays.append((len(base64.b64decode(pcm_base64)), sample_rate, channels))
        return {"ok": True}


def test_speaker_plays_phrases_in_order() -> None:
    backend = FakeBackend()
    bridge = FakeBridge()
    speaker = Speaker(backend, bridge)
    try:
        assert speaker.say("первая фраза")
        assert speaker.say("вторая фраза")
        assert speaker.wait_idle(5)
    finally:
        speaker.close()
    assert backend.texts == ["первая фраза", "вторая фраза"]
    assert len(bridge.plays) == 4
    assert bridge.plays[0] == (20, 22050, 1)


def test_speaker_drops_stale_pending_cue() -> None:
    backend = FakeBackend()
    backend.block = True
    bridge = FakeBridge()
    speaker = Speaker(backend, bridge, max_pending=1)
    try:
        speaker.say("сейчас")
        deadline = time.monotonic() + 2
        while not backend.texts and time.monotonic() < deadline:
            time.sleep(0.01)
        speaker.say("устарела")
        speaker.say("новая")
        backend.release.set()
        assert speaker.wait_idle(5)
    finally:
        backend.release.set()
        speaker.close()
    assert backend.texts == ["сейчас", "новая"]


def test_cache_roundtrip(tmp_path) -> None:
    cache = PcmCache(tmp_path)
    chunks = [AudioChunk(pcm=b"\x01\x02" * 4, sample_rate=22050, channels=1)]
    cache.put("piper:irina", "привет", chunks)
    cached = cache.get("piper:irina", "привет")
    assert cached is not None
    assert cached[0].pcm == chunks[0].pcm
    assert cached[0].sample_rate == 22050
    assert cache.get("piper:other", "привет") is None
    assert cache.get("piper:irina", "нет в кэше") is None


def test_cache_skips_long_text(tmp_path) -> None:
    cache = PcmCache(tmp_path, max_text_len=5)
    cache.put("v", "длинный текст", [AudioChunk(pcm=b"\x00\x00", sample_rate=22050)])
    assert cache.get("v", "длинный текст") is None


def test_piper_backend_reports_missing_model(tmp_path) -> None:
    backend = PiperBackend(tmp_path / "missing.onnx")
    try:
        list(backend.stream("привет"))
    except FileNotFoundError as exc:
        assert "missing.onnx" in str(exc)
    else:
        raise AssertionError("FileNotFoundError expected")
