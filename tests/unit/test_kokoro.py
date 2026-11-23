"""Unit tests for the Kokoro backend wiring (no model needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from voice.kokoro_backend import KokoroBackend
from voice.text import split_sentences


def test_split_sentences_keeps_punctuation() -> None:
    assert split_sentences("Привет! Как дела? Хорошо.") == [
        "Привет!",
        "Как дела?",
        "Хорошо.",
    ]


def test_split_sentences_splits_long_text() -> None:
    text = "Первая часть, " + "очень длинная фраза " * 20 + "конец."
    parts = split_sentences(text, max_chars=80)
    assert len(parts) > 1
    assert all(len(part) <= 120 for part in parts)


def test_kokoro_backend_missing_assets(tmp_path: Path) -> None:
    backend = KokoroBackend(tmp_path, voice="sveta")
    with pytest.raises((FileNotFoundError, ImportError)):
        list(backend.stream("Привет"))
