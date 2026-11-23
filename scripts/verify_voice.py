#!/usr/bin/env python3
"""Check the local voice: synthesize a Russian phrase, measure speed, save WAV.

Run in WSL:
    .venv/bin/python scripts/verify_voice.py

With the bridge up and VB-Cable installed you can also play it:
    .venv/bin/python scripts/verify_voice.py --play
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from perception.bridge_client import BridgeClient  # noqa: E402
from voice.piper_backend import PiperBackend  # noqa: E402
from voice.speaker import Speaker  # noqa: E402

TEXT = "Привет! Это Пилот. Я умею говорить локально, без интернета и без платных сервисов."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--play", action="store_true", help="stream the phrase to the bridge")
    parser.add_argument("--text", default=TEXT)
    args = parser.parse_args()

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    voice_config = config.get("voice", {})
    piper_config = voice_config.get("piper", {})
    model_path = ROOT / piper_config.get("model", "models/piper/ru_RU-irina-medium.onnx")

    started = time.perf_counter()
    backend = PiperBackend(
        model_path,
        length_scale=float(piper_config.get("length_scale", 1.0)),
        volume=float(piper_config.get("volume", 1.0)),
    )
    chunks = list(backend.stream(args.text))
    synth_s = time.perf_counter() - started
    if not chunks:
        print("FAIL: no audio produced")
        return 1
    pcm = b"".join(chunk.pcm for chunk in chunks)
    first = chunks[0]
    duration = len(pcm) / (first.sample_rate * max(1, first.sample_width) * max(1, first.channels))
    rtf = synth_s / duration if duration else 0.0

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = ROOT / "runs" / "voice-test"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"voice-{stamp}.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(first.channels)
        wav_file.setsampwidth(first.sample_width)
        wav_file.setframerate(first.sample_rate)
        wav_file.writeframes(pcm)

    result = {
        "backend": backend.name,
        "text": args.text,
        "chunks": len(chunks),
        "sample_rate": first.sample_rate,
        "channels": first.channels,
        "audio_s": round(duration, 2),
        "synth_s": round(synth_s, 3),
        "rtf": round(rtf, 3),
        "wav": str(wav_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    played = False
    if args.play:
        class ReplayBackend:
            name = backend.name

            def stream(self, text: str):
                yield from chunks

        client = BridgeClient.discover()
        before = client.status().get("audio_bytes", 0)
        speaker = Speaker(ReplayBackend(), client)
        try:
            speaker.say(args.text)
            played = speaker.wait_idle(60)
        finally:
            speaker.close()
        after = client.status().get("audio_bytes", 0)
        client.close()
        print("streamed to bridge:", played, "bytes added:", after - before)
        played = played and (after - before) >= len(pcm)

    (out_dir / f"verify-{stamp}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ok = duration > 2 and rtf < 1.0 and first.sample_rate >= 16000
    if args.play:
        ok = ok and played
    print("VOICE: PASS" if ok else "VOICE: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
