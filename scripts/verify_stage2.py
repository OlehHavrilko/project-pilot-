#!/usr/bin/env python3
"""Stage 2 acceptance check: numbered text observations for OBS, Explorer and Discord.

UIA is used for OBS and Explorer, CDP for Discord. Also checks that window
open/close events arrive over the bridge WebSocket.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from perception.bridge_client import BridgeClient, BridgeError  # noqa: E402
from perception.cdp import CdpError  # noqa: E402
from perception.cdp import snapshot as cdp_snapshot  # noqa: E402
from perception.render import render_ax_tree, render_snapshot  # noqa: E402

POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


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


def observe_text(client: BridgeClient, window: str, max_elements: int = 250) -> str:
    return render_snapshot(
        client.observe(window=window, max_elements=max_elements, depth=8), max_per_window=30
    )


def main() -> int:
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = ROOT / "runs" / f"stage2-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    checks = Checks()
    client = BridgeClient.discover()
    host = client.base_url.split("//", 1)[1].split(":", 1)[0]
    explorer_started = False
    try:
        # --- OBS (UIA) ---------------------------------------------------
        obs_text = ""
        try:
            obs_text = observe_text(client, "OBS")
        except BridgeError as exc:
            checks.check("OBS window observed", False, str(exc))
        (run_dir / "obs.txt").write_text(obs_text, encoding="utf-8")
        checks.check("OBS window observed", bool(obs_text), f"{len(obs_text)} chars")
        obs_words = ("Начать запись", "Записать", "Настройки", "Сцены")
        obs_ok = any(word in obs_text for word in obs_words)
        checks.check(
            "OBS elements are readable", obs_ok, obs_text.splitlines()[0] if obs_text else ""
        )

        # --- Explorer (UIA) ----------------------------------------------
        explorer_text = ""
        try:
            explorer_text = observe_text(client, "Video")
        except BridgeError:
            powershell("Start-Process explorer.exe 'D:\\Video'")
            explorer_started = True
            time.sleep(2.5)
            try:
                explorer_text = observe_text(client, "Video")
            except BridgeError as exc:
                checks.check("Explorer window observed", False, str(exc))
        (run_dir / "explorer.txt").write_text(explorer_text, encoding="utf-8")
        checks.check("Explorer window observed", bool(explorer_text), f"{len(explorer_text)} chars")
        explorer_words = ("Элементов", "Видео", "Video", "проводник")
        checks.check(
            "Explorer elements are readable",
            any(word in explorer_text for word in explorer_words),
        )

        # --- Discord (CDP) -----------------------------------------------
        discord_text = ""
        try:
            title, nodes = cdp_snapshot(host, 9223, title_filter="Discord")
            discord_text = render_ax_tree(title, nodes)
        except CdpError as exc:
            checks.check("Discord CDP snapshotted", False, str(exc))
        (run_dir / "discord.txt").write_text(discord_text, encoding="utf-8")
        checks.check("Discord CDP snapshotted", bool(discord_text), f"{len(discord_text)} chars")
        checks.check(
            "Discord elements are readable",
            "button" in discord_text and ("textbox" in discord_text or "Вход" in discord_text),
        )

        # --- events ------------------------------------------------------
        powershell("Start-Process notepad.exe")
        time.sleep(1.0)
        opened = client.watch_events(seconds=6)
        open_hits = [
            event
            for event in opened
            if event.get("type") == "window_open" and "Блокнот" in event.get("title", "")
        ]
        checks.check("window_open event received", bool(open_hits), str(open_hits[:1]))
        thread = threading.Timer(
            1.0,
            lambda: powershell(
                "Get-Process notepad -ErrorAction SilentlyContinue | Stop-Process -Force"
            ),
        )
        thread.start()
        closed = client.watch_events(seconds=6)
        thread.join(timeout=5)
        close_hits = [
            event
            for event in closed
            if event.get("type") == "window_close" and "Блокнот" in event.get("title", "")
        ]
        checks.check("window_close event received", bool(close_hits), str(close_hits[:1]))

        if explorer_started:
            powershell(
                "Get-Process explorer | Where-Object { $_.MainWindowTitle -like '*Video*' } "
                "| ForEach-Object { $_.CloseMainWindow() }"
            )

        report = {
            "stage": 2,
            "passed": checks.ok,
            "checks": checks.items,
            "artifacts": ["obs.txt", "explorer.txt", "discord.txt"],
        }
        (run_dir / "verify.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        client.close()

    print()
    print(f"artifact: {run_dir}")
    print("STAGE 2: PASS" if checks.ok else "STAGE 2: FAIL")
    return 0 if checks.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
