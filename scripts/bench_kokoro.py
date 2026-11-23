#!/usr/bin/env python3
"""Benchmark Kokoro-ru on the current machine (GPU if available).

Example on Windows (ROCm PyTorch venv):
    python scripts/bench_kokoro.py --asset-dir "%LOCALAPPDATA%\\pilot\\kokoro"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from voice.kokoro_backend import KokoroBackend  # noqa: E402

TEXT = "Привет! Это Пилот. Я умею говорить локально на видеокарте RX 9060 XT."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", default=str(ROOT / "models" / "kokoro"))
    parser.add_argument("--voice", default="sveta")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--text", default=TEXT)
    parser.add_argument("--out", default=str(ROOT / "runs" / "kokoro-bench.wav"))
    args = parser.parse_args()

    backend = KokoroBackend(args.asset_dir, voice=args.voice, device=args.device)
    started = time.perf_counter()
    backend.warmup()
    warmup_s = time.perf_counter() - started

    pcm = b""
    timings = []
    for _ in range(args.runs):
        chunk_pcm = b""
        t0 = time.perf_counter()
        for chunk in backend.stream(args.text):
            chunk_pcm += chunk.pcm
        timings.append(time.perf_counter() - t0)
        pcm = chunk_pcm
    duration = len(pcm) / (24000 * 2)
    best = min(timings)
    result = {
        "backend": backend.name,
        "device": backend.device,
        "warmup_s": round(warmup_s, 2),
        "audio_s": round(duration, 2),
        "synth_s": [round(t, 3) for t in timings],
        "best_rtf": round(best / duration, 3),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(pcm)
    result["wav"] = str(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = duration > 1 and best / duration < 1.0
    print("KOKORO: PASS" if ok else "KOKORO: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
