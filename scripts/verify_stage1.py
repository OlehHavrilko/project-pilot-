#!/usr/bin/env python3
"""Stage 1 acceptance check: record 30 s with separate system and voice tracks.

Requires: OBS running with obs-websocket enabled, VB-Cable installed, the bridge
deployed with PILOT_AUDIO_DEVICE="CABLE Input", and the Piper voice downloaded.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from perception.bridge_client import BridgeClient  # noqa: E402
from recording.obs_client import ObsClient, ObsError  # noqa: E402
from voice.piper_backend import PiperBackend  # noqa: E402
from voice.speaker import Speaker  # noqa: E402

POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
SYSTEM_NAME = "Звук раб. стола"
VOICE_NAME = "Голос пилота"
MIC_NAME = "Микро"
PHRASES = [
    "Привет! Это Пилот.",
    "Я записываю звук системы и свой голос на разные дорожки.",
    "Так голос можно обработать отдельно от звука игры.",
    "Проверка связи завершена.",
]


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.items)


def powershell(command: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def play_system_sound(times: int = 2) -> None:
    for _ in range(times):
        powershell(
            "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\Windows Ding.wav').PlaySync()"
        )
        time.sleep(2.0)


def find_new_recording(directory_windows: str, since: float) -> Path | None:
    base = Path(
        subprocess.run(
            ["wslpath", "-u", directory_windows], capture_output=True, text=True, check=False
        ).stdout.strip()
    )
    candidates = [base, base.parent / "recordly"] if base else []
    best: Path | None = None
    for folder in candidates:
        if not folder.exists():
            continue
        for path in folder.glob("*.mkv"):
            mtime = path.stat().st_mtime
            if mtime >= since and (best is None or mtime > best.stat().st_mtime):
                best = path
    return best


def ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return round(float(result.stdout.strip()), 2)
    except ValueError:
        return 0.0


def audio_tracks(path: Path) -> list[dict]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-select_streams", "a",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(result.stdout or "{}").get("streams", [])


def track_sound_seconds(path: Path, index: int) -> float:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", f"0:a:{index}",
            "-af", "silencedetect=noise=-45dB:d=1.0", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    duration = ffprobe_duration(path)
    silence = sum(
        float(match) for match in re.findall(r"silence_duration: ([0-9.]+)", result.stderr)
    )
    return max(0.0, duration - silence)


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = ROOT / "runs" / f"stage1-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    checks = Checks()
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    try:
        obs = ObsClient.connect()
    except ObsError as exc:
        print(f"FAIL: {exc}")
        return 1

    bridge = None
    speaker = None
    try:
        checks.check("OBS websocket connected", True, f"OBS {obs.version()}")
        mask = obs.enable_recording_tracks(7)
        checks.check("recording tracks 1+2+3 enabled", mask == 7, f"RecTracks={mask}")

        inputs = obs.audio_inputs()
        checks.check(f"input '{SYSTEM_NAME}' exists", SYSTEM_NAME in inputs, str(list(inputs)))
        checks.check(
            f"input '{VOICE_NAME}' exists", VOICE_NAME in inputs, str(list(inputs))
        )
        if SYSTEM_NAME in inputs:
            obs.set_input_tracks(SYSTEM_NAME, {1})
            obs.unmute(SYSTEM_NAME)
            checks.check("system audio on track 1", obs.audio_inputs()[SYSTEM_NAME]["1"])
        if VOICE_NAME in inputs:
            obs.set_input_tracks(VOICE_NAME, {2})
            obs.unmute(VOICE_NAME)
            checks.check("agent voice on track 2", obs.audio_inputs()[VOICE_NAME]["2"])
        mic_present = MIC_NAME in inputs
        if mic_present:
            obs.set_input_tracks(MIC_NAME, {3})
            obs.unmute(MIC_NAME)
            checks.check("microphone on track 3", obs.audio_inputs()[MIC_NAME]["3"])
        else:
            checks.check("microphone on track 3", True, "mic input not configured, skipped")

        bridge = BridgeClient.discover()
        status = bridge.status()
        checks.check(
            "bridge plays into VB-Cable",
            status.get("audio_device") == "CABLE Input",
            str(status.get("audio_device")),
        )

        piper = config["voice"]["piper"]
        backend = PiperBackend(
            ROOT / piper["model"], length_scale=float(piper.get("length_scale", 1.0))
        )
        speaker = Speaker(backend, bridge)

        started_wall = time.time()
        obs.start_recording()
        started = False
        for _ in range(20):
            if obs.recording():
                started = True
                break
            time.sleep(0.25)
        checks.check("recording started", started)
        time.sleep(1.0)
        play_system_sound(times=2)
        for phrase in PHRASES:
            speaker.say(phrase)
            time.sleep(5.5)
        speaker.wait_idle(30)
        elapsed = time.time() - started_wall
        if elapsed < 30:
            time.sleep(30 - elapsed)
        obs.stop_recording()
        stopped = False
        for _ in range(20):
            if not obs.recording():
                stopped = True
                break
            time.sleep(0.25)
        checks.check("recording stopped", stopped)

        directory = obs.recording_dir_windows()
        path = find_new_recording(directory, started_wall - 5)
        checks.check("new recording found", path is not None, str(path))
        if path is None:
            return 1

        streams = audio_tracks(path)
        checks.check("audio streams >= 2", len(streams) >= 2, f"{len(streams)} audio tracks")
        sound = [round(track_sound_seconds(path, index), 1) for index in range(len(streams))]
        checks.check("system track has sound", sound[0] > 0.5 if sound else False, f"{sound}")
        if len(sound) > 1:
            checks.check("voice track has sound", sound[1] > 0.5, f"{sound[1]} s")
        if len(sound) > 2:
            checks.check(
                "microphone track present (may be silent)", True, f"{sound[2]} s"
            )
        duration = ffprobe_duration(path)
        report = {
            "stage": 1,
            "passed": checks.ok,
            "file": str(path),
            "duration_s": duration,
            "audio_tracks": len(streams),
            "sound_seconds": sound,
            "checks": checks.items,
        }
        (run_dir / "verify.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        if speaker is not None:
            speaker.close()
        if bridge is not None:
            bridge.close()
        obs.close()

    print()
    print(f"artifact: {run_dir}")
    print("STAGE 1: PASS" if checks.ok else "STAGE 1: FAIL")
    return 0 if checks.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
