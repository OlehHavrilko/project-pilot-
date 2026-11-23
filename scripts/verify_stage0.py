#!/usr/bin/env python3
"""Stage 0 acceptance check: WSL -> Windows bridge -> Notepad.

Criterion (PROJECT_PILOT.md):
  from WSL we get the element list of the Notepad window, type text into it,
  take a screenshot, and the stop hotkey aborts a series of actions.

Run inside WSL while the bridge is up:
    .venv/bin/python scripts/verify_stage0.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from perception.bridge_client import BridgeClient, BridgeError, BridgeStopped  # noqa: E402

POWERSHELL = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
WINDOW_FILTERS = ("Блокнот", "Notepad", "notepad")
TEST_TEXT = "Привет, Пилот! Hello, Pilot 123."
HOTKEY_SCRIPT = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PilotKeys {
  [DllImport("user32.dll")]
  public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
}
"@
$down = 0
$up = 2
[PilotKeys]::keybd_event(0x11, 0, $down, [UIntPtr]::Zero)   # Ctrl
[PilotKeys]::keybd_event(0x12, 0, $down, [UIntPtr]::Zero)   # Alt
[PilotKeys]::keybd_event(0x51, 0, $down, [UIntPtr]::Zero)   # Q
Start-Sleep -Milliseconds 60
[PilotKeys]::keybd_event(0x51, 0, $up, [UIntPtr]::Zero)
[PilotKeys]::keybd_event(0x12, 0, $up, [UIntPtr]::Zero)
[PilotKeys]::keybd_event(0x11, 0, $up, [UIntPtr]::Zero)
"""


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "ok": bool(condition), "detail": detail})
        print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return bool(condition)

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.items)


def powershell(command: str, timeout: float = 40.0) -> subprocess.CompletedProcess:
    if not POWERSHELL.exists():
        raise RuntimeError(f"PowerShell not found at {POWERSHELL}; mount Windows drives first")
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def launch_notepad() -> None:
    result = powershell("Start-Process notepad.exe")
    if result.returncode != 0:
        raise RuntimeError(f"cannot launch Notepad: {result.stderr.strip()}")


def press_stop_hotkey() -> None:
    result = powershell(HOTKEY_SCRIPT, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(f"cannot send hotkey: {result.stderr.strip()}")


def read_clipboard() -> str:
    result = powershell("Get-Clipboard -Raw")
    return result.stdout.strip()


def observe_notepad(client: BridgeClient, timeout: float = 20.0) -> tuple[dict, str] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for candidate in WINDOW_FILTERS:
            try:
                snapshot = client.observe(window=candidate, max_elements=300, depth=8)
            except BridgeError:
                continue
            if snapshot.get("elements"):
                return snapshot, candidate
        time.sleep(0.5)
    return None


def pick_edit(snapshot: dict) -> dict | None:
    candidates = [
        element
        for element in snapshot["elements"]
        if element.get("control_type") in ("Edit", "Document", "Text")
    ]
    if not candidates:
        return None
    focused = [element for element in candidates if element.get("focused")]
    return (focused or candidates)[0]


def element_text(element: dict) -> str:
    return "\n".join(
        part for part in (element.get("value"), element.get("text")) if part
    )


def snapshot_text(snapshot: dict) -> str:
    return "\n".join(element_text(element) for element in snapshot["elements"])


def ffprobe_size(path: Path) -> str:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or result.stderr.strip()


def stop_notepad(snapshot: dict) -> None:
    process_ids = {
        window.get("process_id")
        for window in snapshot.get("windows", [])
        if window.get("process_id")
    }
    for process_id in process_ids:
        powershell(f"Stop-Process -Id {process_id} -Force -ErrorAction SilentlyContinue")


def main() -> int:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = ROOT / "runs" / f"stage0-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    checks = Checks()

    try:
        client = BridgeClient.discover()
    except BridgeError as exc:
        print(f"FAIL: {exc}")
        print("Hint: scripts/bridge.sh deploy")
        return 1

    try:
        status = client.status()
        checks.check("bridge answers /status", status.get("ok") is True, client.base_url)
        checks.check(
            "stop hotkey registered",
            bool(status.get("hotkey_registered")),
            str(status.get("hotkey")),
        )

        launch_notepad()
        found = observe_notepad(client)
        checks.check("Notepad window observed", found is not None)
        if not found:
            return 1
        snapshot, window_filter = found
        (run_dir / "observe.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        edit = pick_edit(snapshot)
        control_type = edit.get("control_type") if edit else None
        checks.check(
            "editable element found",
            edit is not None,
            f"{len(snapshot['elements'])} elements, control_type={control_type}",
        )
        if not edit:
            return 1

        focused = False
        for _ in range(2):
            client.act({"action": "focus_window", "window": window_filter})
            client.act({"action": "focus", "id": edit["id"]})
            time.sleep(0.3)
            focus_check = client.observe(window=window_filter, max_elements=300, depth=8)
            focused = window_filter.lower() in (
                focus_check.get("active_window") or ""
            ).lower()
            if focused:
                break

        powershell("Set-Clipboard -Value 'pilot-clipboard-clear'")
        if focused:
            client.act({"action": "type_text", "text": TEST_TEXT})
            typed_via = "keyboard (type_text)"
        else:
            client.act({"action": "set_text", "id": edit["id"], "text": TEST_TEXT})
            typed_via = "UIA/WM_SETTEXT (another window kept the foreground)"
        time.sleep(0.4)

        after = client.observe(window=window_filter, max_elements=300, depth=8)
        typed_ok = TEST_TEXT in snapshot_text(after)
        if not typed_ok:
            client.act({"action": "key", "keys": "^a"})
            client.act({"action": "key", "keys": "^c"})
            time.sleep(0.2)
            typed_ok = TEST_TEXT in read_clipboard()
        checks.check("text typed into Notepad", typed_ok, typed_via)

        png = client.screenshot(window=window_filter)
        png_path = run_dir / "notepad.png"
        png_path.write_bytes(png)
        size = ffprobe_size(png_path)
        checks.check(
            "screenshot captured",
            len(png) > 5000 and "x" not in size and "," in size,
            f"{len(png)} bytes, frame {size}",
        )

        client.resume()
        steps = [{"action": "wait", "seconds": 0.25} for _ in range(40)]
        result: dict = {}

        def run_series() -> None:
            try:
                result["value"] = client.act(steps)
            except BridgeStopped as exc:
                result["stopped"] = exc
            except Exception as exc:  # noqa: BLE001 - reported below
                result["error"] = exc

        worker = threading.Thread(target=run_series, daemon=True)
        worker.start()
        time.sleep(1.0)
        press_stop_hotkey()
        worker.join(timeout=30)
        stopped = result.get("stopped")
        failure_detail = str(result.get("error") or result.get("value"))[:200]
        checks.check(
            "stop hotkey aborts action series",
            stopped is not None,
            f"executed {stopped.executed} of 40" if stopped else failure_detail,
        )
        if stopped is not None:
            checks.check("aborted before the end", stopped.executed < 40, str(stopped.executed))
            checks.check("bridge reports stopped state", client.status().get("stopped") is True)

        client.resume()
        checks.check(
            "actions work again after resume",
            client.act({"action": "wait", "seconds": 0.1}).get("ok") is True,
        )

        stop_notepad(snapshot)
    finally:
        client.close()

    summary = {
        "stage": 0,
        "passed": checks.ok,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "bridge": client.base_url,
        "checks": checks.items,
    }
    (run_dir / "verify.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print()
    print(f"artifact: {run_dir}")
    print("STAGE 0: PASS" if checks.ok else "STAGE 0: FAIL")
    return 0 if checks.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
