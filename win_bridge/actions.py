"""Low-level Windows input: UIA patterns, unicode typing, keyboard shortcuts."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from pywinauto import keyboard as pwa_keyboard

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class ActionError(Exception):
    """An action cannot be performed on the target element."""


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


def _key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return event


def _send(events: list[INPUT]) -> None:
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise ActionError(f"SendInput accepted {sent}/{len(events)} events")


def type_unicode(text: str) -> None:
    """Type arbitrary unicode text through the keyboard input queue."""
    for char in text:
        if char == "\n":
            _send([_key_event(vk=VK_RETURN), _key_event(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)])
            continue
        if char == "\t":
            _send([_key_event(vk=VK_TAB), _key_event(vk=VK_TAB, flags=KEYEVENTF_KEYUP)])
            continue
        if char == "\r":
            continue
        encoded = char.encode("utf-16-le")
        for index in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[index : index + 2], "little")
            _send(
                [
                    _key_event(scan=unit, flags=KEYEVENTF_UNICODE),
                    _key_event(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                ]
            )


def send_keys(keys: str) -> None:
    """Send a pywinauto keyboard shortcut, for example '^a' or '{ENTER}'."""
    try:
        pwa_keyboard.send_keys(keys)
    except Exception as exc:  # noqa: BLE001 - pywinauto raises various errors
        raise ActionError(f"cannot send keys {keys!r}: {exc}") from exc


def click(element) -> None:
    try:
        element.invoke()
        return
    except Exception:  # noqa: BLE001 - element may not support Invoke
        pass
    try:
        element.click_input()
    except Exception as exc:  # noqa: BLE001
        raise ActionError(f"click failed: {exc}") from exc


def set_text(element, text: str) -> None:
    try:
        element.iface_value.SetValue(text)
        return
    except Exception:  # noqa: BLE001 - element may not support ValuePattern
        pass
    try:
        control_type = element.element_info.control_type
        hwnd = element.element_info.handle
        if hwnd and control_type in ("Edit", "Document"):
            # WM_SETTEXT works for edit controls even when their window is not foreground.
            user32.SendMessageW(hwnd, 0x000C, 0, ctypes.c_wchar_p(text))
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        element.set_focus()
        time.sleep(0.05)
        send_keys("^a")
        type_unicode(text)
    except Exception as exc:  # noqa: BLE001
        raise ActionError(f"set_text failed: {exc}") from exc


def focus(element) -> None:
    try:
        element.set_focus()
        time.sleep(0.1)
    except Exception as exc:  # noqa: BLE001
        raise ActionError(f"focus failed: {exc}") from exc
