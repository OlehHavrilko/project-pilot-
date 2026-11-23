"""Play PCM16 audio chunks on a chosen Windows output device."""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)


class AudioPlayer:
    def __init__(self, device: str | None = None) -> None:
        self.device = device
        self._sd = None
        self._resolved = None

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
                    return index
            logger.warning("audio device %r not found, using default", device)
        except Exception:
            logger.exception("cannot enumerate audio devices")
        return None

    @property
    def available(self) -> bool:
        try:
            sd = self._load()
            return sd is not None
        except Exception:
            return False

    def play_pcm(self, pcm_base64: str, sample_rate: int = 24000, channels: int = 1) -> None:
        pcm = base64.b64decode(pcm_base64)
        sd = self._load()
        stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            device=self._resolved,
        )
        with stream:
            stream.write(pcm)
