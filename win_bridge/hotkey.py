"""Global stop hotkey via RegisterHotKey (no elevation required)."""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

from actions import send_keys

logger = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

user32 = ctypes.WinDLL("user32", use_last_error=True)


def _parse_combo(combo: str) -> tuple[int, int]:
    """Parse 'ctrl+alt+q' into (modifiers, virtual-key code)."""
    parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
    if not parts:
        raise ValueError(f"empty hotkey: {combo!r}")
    mods = 0
    key = parts[-1]
    for part in parts[:-1]:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= 0x0004
        elif part in ("win", "meta"):
            mods |= 0x0008
        else:
            raise ValueError(f"unknown modifier in hotkey: {part!r}")
    if len(key) != 1:
        raise ValueError(f"unsupported hotkey key: {key!r}")
    vk = ord(key.upper())
    return mods | MOD_NOREPEAT, vk


class HotkeyListener:
    """Register a system-wide hotkey and call ``on_trigger`` from its own thread."""

    def __init__(self, combo: str, on_trigger) -> None:
        self.combo = combo
        self.on_trigger = on_trigger
        self.registered = False
        self._mods, self._vk = _parse_combo(combo)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()

    def start(self, wait_s: float = 3.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="pilot-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(wait_s)
        return self.registered

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self._mods, self._vk):
            logger.error(
                "cannot register hotkey %s (error %s)", self.combo, ctypes.get_last_error()
            )
            self._ready.set()
            return
        self.registered = True
        logger.info("stop hotkey registered: %s", self.combo)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    logger.warning("stop hotkey pressed")
                    try:
                        self.on_trigger()
                    except Exception:
                        logger.exception("hotkey handler failed")
        finally:
            user32.UnregisterHotKey(None, 1)
            logger.info("stop hotkey released")


def press_hotkey_for_tests(combo: str = "ctrl+alt+q") -> None:
    """Send the combo through the normal keyboard input queue (used by tests only)."""
    parts = [part.strip() for part in combo.split("+") if part.strip()]
    mods = "".join(
        "^" if p.lower() in ("ctrl", "control") else "%"
        for p in parts[:-1]
        if p.lower() in ("ctrl", "control", "alt")
    )
    send_keys(mods + parts[-1])
