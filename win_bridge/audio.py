"""Play PCM16 audio chunks on a chosen Windows output device.

Streams stay open while chunks keep arriving, so consecutive TTS chunks play
without gaps. ``dry_run`` accepts and counts audio without touching a device
(useful in tests and on machines without VB-Cable).
"""

from __future__ import annotations

import base64
import logging
import queue
import threading

logger = logging.getLogger(__name__)


class AudioPlayer:
    def __init__(self, device: str | None = None, dry_run: bool = False) -> None:
        self.device = device
        self.dry_run = dry_run
        self._sd = None
        self._resolved = None
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False
        self.bytes_played = 0
        self._lock = threading.Lock()

    def _load(self):
        if self._sd is None:
            import sounddevice

            self._sd = sounddevice
            self._resolved = self._resolve_device()
        return self._sd

    def _resolve_device(self):
        device = self.device
        if not device:
            return None
        try:
            for index, info in enumerate(self._sd.query_devices()):
                if device.lower() in info["name"].lower() and info["max_output_channels"] > 0:
                    logger.info("audio output device: %s", info["name"])
                    return index
            logger.warning("audio device %r not found, using default", device)
        except Exception:  # noqa: BLE001 - device enumeration is best-effort
            logger.exception("cannot enumerate audio devices")
        return None

    @property
    def available(self) -> bool:
        if self.dry_run:
            return True
        try:
            self._load()
            return True
        except Exception:  # noqa: BLE001
            return False

    def play_pcm(self, pcm_base64: str, sample_rate: int = 24000, channels: int = 1) -> None:
        pcm = base64.b64decode(pcm_base64)
        if not pcm:
            return
        with self._lock:
            self.bytes_played += len(pcm)
        if self.dry_run:
            return
        self._ensure_worker()
        self._queue.put((pcm, sample_rate, channels))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout=5.0)

    def _ensure_worker(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="pilot-audio", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sd = self._load()
        stream = None
        current_format: tuple[int, int] | None = None
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                pcm, sample_rate, channels = item
                if current_format != (sample_rate, channels):
                    if stream is not None:
                        stream.close()
                    stream = sd.RawOutputStream(
                        samplerate=sample_rate,
                        channels=channels,
                        dtype="int16",
                        device=self._resolved,
                    )
                    stream.start()
                    current_format = (sample_rate, channels)
                stream.write(pcm)
        except Exception:  # noqa: BLE001 - a dead device must not kill the bridge
            logger.exception("audio playback failed")
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
