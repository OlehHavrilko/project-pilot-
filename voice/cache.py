"""Disk cache for short, frequently repeated phrases."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from voice.tts import AudioChunk

logger = logging.getLogger(__name__)


class PcmCache:
    """Store synthesized PCM on disk so repeated phrases are free."""

    def __init__(self, directory: str | Path, max_text_len: int = 160) -> None:
        self.directory = Path(directory)
        self.max_text_len = max_text_len

    def _key(self, voice: str, text: str) -> str:
        digest = hashlib.sha256(f"{voice}\x00{text}".encode()).hexdigest()[:24]
        return digest

    def get(self, voice: str, text: str) -> tuple[AudioChunk, ...] | None:
        if len(text) > self.max_text_len:
            return None
        key = self._key(voice, text)
        pcm_path = self.directory / f"{key}.pcm"
        meta_path = self.directory / f"{key}.json"
        if not pcm_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            pcm = pcm_path.read_bytes()
        except (OSError, ValueError):
            logger.warning("cannot read voice cache entry %s", key)
            return None
        if not pcm:
            return None
        return (
            AudioChunk(
                pcm=pcm,
                sample_rate=int(meta["sample_rate"]),
                sample_width=int(meta.get("sample_width", 2)),
                channels=int(meta.get("channels", 1)),
            ),
        )

    def put(self, voice: str, text: str, chunks: list[AudioChunk]) -> None:
        if not chunks or len(text) > self.max_text_len:
            return
        pcm = b"".join(chunk.pcm for chunk in chunks)
        if not pcm:
            return
        first = chunks[0]
        key = self._key(voice, text)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / f"{key}.pcm").write_bytes(pcm)
            (self.directory / f"{key}.json").write_text(
                json.dumps(
                    {
                        "voice": voice,
                        "text": text,
                        "sample_rate": first.sample_rate,
                        "sample_width": first.sample_width,
                        "channels": first.channels,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("cannot write voice cache entry %s", key)
