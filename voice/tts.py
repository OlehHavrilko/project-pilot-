"""Local text-to-speech: audio chunks, backend protocol and helpers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioChunk:
    """A piece of raw PCM audio produced by a TTS backend."""

    pcm: bytes
    sample_rate: int
    sample_width: int = 2
    channels: int = 1


class TTSBackend(Protocol):
    """Anything that can turn text into a stream of PCM chunks."""

    name: str

    def stream(self, text: str) -> Iterator[AudioChunk]:
        """Yield audio chunks in order. Must not block on playback."""
