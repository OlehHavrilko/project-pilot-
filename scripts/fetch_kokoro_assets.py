#!/usr/bin/env python3
"""Download Kokoro-ru model, voice packs and acute-aware espeak data.

Run once on the machine that synthesizes speech (Windows for GPU):
    python scripts/fetch_kokoro_assets.py --asset-dir models/kokoro
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import snapshot_download

PATTERNS = [
    "kokoro-ru-v2-base.pth",
    "kokoro-ru-v2-dima.pth",
    "config.json",
    "kokoro-config.json",
    "voices/*.pt",
    "espeak-data/**",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", default="models/kokoro")
    parser.add_argument("--repo", default="zaakirio/kokoro-ru")
    args = parser.parse_args()
    target = Path(args.asset_dir)
    target.mkdir(parents=True, exist_ok=True)
    print(f"downloading {args.repo} -> {target}")
    path = snapshot_download(
        args.repo,
        local_dir=target,
        allow_patterns=PATTERNS,
        token=os.environ.get("HF_TOKEN"),
    )
    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"done: {path} ({total / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
