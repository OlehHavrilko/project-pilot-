"""Queued voiceover: synthesize phrases and stream them to the bridge."""

from __future__ import annotations

import base64
import logging
import threading
import time
from collections import deque

from voice.cache import PcmCache
from voice.tts import AudioChunk, TTSBackend

logger = logging.getLogger(__name__)


class Speaker:
    """A small FIFO of lines. The newest lines are heard after the current one."""

    def __init__(
        self,
        backend: TTSBackend,
        bridge,
        cache: PcmCache | None = None,
        max_pending: int = 2,
    ) -> None:
        self._backend = backend
        self._bridge = bridge
        self._cache = cache
        self._max_pending = max(1, max_pending)
        self._queue: deque[str] = deque()
        self._cv = threading.Condition()
        self._busy = False
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="pilot-voice", daemon=True)
        self._thread.start()

    @property
    def pending(self) -> int:
        with self._cv:
            return len(self._queue) + (1 if self._busy else 0)

    def say(self, text: str) -> bool:
        cleaned = " ".join(text.split())
        if not cleaned:
            return False
        with self._cv:
            if self._closed:
                return False
            if len(self._queue) >= self._max_pending:
                dropped = self._queue.popleft()
                logger.info("dropping stale cue: %r", dropped[:60])
            self._queue.append(cleaned)
            self._cv.notify()
        return True

    def wait_idle(self, timeout: float = 120.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._cv:
            while (self._queue or self._busy) and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
        return not self._closed

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()
        self._thread.join(timeout=5.0)

    # -- worker -----------------------------------------------------------

    def _take(self) -> str | None:
        with self._cv:
            while not self._queue and not self._closed:
                self._cv.wait()
            if self._closed:
                return None
            text = self._queue.popleft()
            self._busy = True
            return text

    def _run(self) -> None:
        warmup = getattr(self._backend, "warmup", None)
        if callable(warmup):
            try:
                warmup()
            except Exception:  # noqa: BLE001 - warmup must not kill the queue
                logger.exception("voice warmup failed")
        while True:
            text = self._take()
            if text is None:
                break
            try:
                self._speak(text)
            except Exception:  # noqa: BLE001 - a failed line must not kill the queue
                logger.exception("voice playback failed for %r", text[:60])
            finally:
                with self._cv:
                    self._busy = False
                    self._cv.notify_all()

    def _speak(self, text: str) -> None:
        cached = self._cache.get(self._backend.name, text) if self._cache else None
        if cached:
            for chunk in cached:
                self._play(chunk)
            return
        chunks: list[AudioChunk] = []
        for chunk in self._backend.stream(text):
            chunks.append(chunk)
            self._play(chunk)
        if self._cache:
            self._cache.put(self._backend.name, text, chunks)

    def _play(self, chunk: AudioChunk) -> None:
        self._bridge.play(
            base64.b64encode(chunk.pcm).decode("ascii"),
            sample_rate=chunk.sample_rate,
            channels=chunk.channels,
        )
