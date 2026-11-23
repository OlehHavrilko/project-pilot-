"""Piper backend: free local neural TTS (ONNX, CPU, Russian voices).

Voices are downloaded separately, for example:
    python -m piper.download_voices ru_RU-irina-medium --download-dir models/piper
"""

from __future__ import annotations

import logging
from pathlib import Path

from voice.tts import AudioChunk

logger = logging.getLogger(__name__)


class PiperBackend:
    def __init__(
        self,
        model_path: str | Path,
        length_scale: float = 1.0,
        volume: float = 1.0,
        noise_scale: float | None = None,
        noise_w_scale: float | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.name = f"piper:{self.model_path.stem}"
        self._length_scale = length_scale
        self._volume = volume
        self._noise_scale = noise_scale
        self._noise_w_scale = noise_w_scale
        self._voice = None
        self._config = None

    def _load(self):
        if self._voice is not None:
            return self._voice, self._config
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Piper voice not found: {self.model_path}. Download it with "
                f"'python -m piper.download_voices {self.model_path.stem} "
                f"--download-dir {self.model_path.parent}'"
            )
        from piper import PiperVoice, SynthesisConfig

        self._voice = PiperVoice.load(self.model_path)
        self._config = SynthesisConfig(
            length_scale=self._length_scale,
            volume=self._volume,
            noise_scale=self._noise_scale,
            noise_w_scale=self._noise_w_scale,
        )
        logger.info("piper voice loaded: %s", self.model_path.name)
        return self._voice, self._config

    def stream(self, text: str):
        if not text.strip():
            return
        voice, config = self._load()
        for chunk in voice.synthesize(text, syn_config=config):
            if not chunk.audio_int16_bytes:
                continue
            yield AudioChunk(
                pcm=chunk.audio_int16_bytes,
                sample_rate=chunk.sample_rate,
                sample_width=chunk.sample_width,
                channels=chunk.sample_channels,
            )
