"""Text helpers for speech: sentence splitting for streaming synthesis."""

from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"[^.!?…]+(?:[.!?…]+[»\"')\]]*|$)")


def split_sentences(text: str, max_chars: int = 220) -> list[str]:
    """Split text into speakable sentences, keeping punctuation.

    Long sentences are split further on commas/semicolons so every chunk stays
    short enough for the Kokoro phoneme window and streams quickly.
    """
    parts = [part.strip() for part in _SENTENCE_RE.findall(text) if part.strip()]
    result: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            result.append(part)
            continue
        current = ""
        for piece in re.split(r"(?<=[,;:])\s+", part):
            candidate = f"{current} {piece}".strip()
            pieces = [candidate] if len(candidate) <= max_chars else _wrap(candidate, max_chars)
            if len(pieces) > 1 or (current and len(candidate) > max_chars):
                if current and not (len(pieces) == 1 and len(candidate) <= max_chars):
                    result.append(current)
                result.extend(pieces[:-1])
                current = pieces[-1]
            else:
                current = candidate
        if current:
            result.append(current)
    return result or ([text.strip()] if text.strip() else [])


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces
