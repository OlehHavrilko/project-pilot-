"""Bridge configuration from command line arguments and environment variables."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeConfig:
    host: str
    port: int
    token: str
    audio_device: str | None
    hotkey: str


def parse_args(argv: list[str] | None = None) -> BridgeConfig:
    parser = argparse.ArgumentParser(description="Pilot Windows bridge")
    parser.add_argument(
        "--host",
        default=os.environ.get("PILOT_BRIDGE_HOST", "127.0.0.1"),
        help="Interface to listen on. Never use 0.0.0.0.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PILOT_BRIDGE_PORT", "8765")),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("PILOT_BRIDGE_TOKEN", ""),
        help="Shared secret. Prefer the PILOT_BRIDGE_TOKEN environment variable.",
    )
    parser.add_argument(
        "--audio-device",
        default=os.environ.get("PILOT_AUDIO_DEVICE") or None,
        help="Substring of the output device name (for example, CABLE Input).",
    )
    parser.add_argument(
        "--hotkey",
        default=os.environ.get("PILOT_STOP_HOTKEY", "ctrl+alt+q"),
    )
    args = parser.parse_args(argv)
    if not args.token:
        parser.error(
            "PILOT_BRIDGE_TOKEN is not set: pass --token or set the environment variable"
        )
    return BridgeConfig(
        host=args.host,
        port=args.port,
        token=args.token,
        audio_device=args.audio_device,
        hotkey=args.hotkey,
    )
