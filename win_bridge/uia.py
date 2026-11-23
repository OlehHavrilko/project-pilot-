"""Windows UI Automation: observations and element addressing.

All UIA calls run on one dedicated thread with COM initialized, because pywinauto
wrappers must be used from the thread that created them.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import comtypes
from pywinauto import Desktop

import actions

logger = logging.getLogger(__name__)

MAX_ELEMENTS_DEFAULT = 200
MAX_DEPTH_DEFAULT = 6



def _force_foreground(hwnd: int) -> None:
    """Bring a window to the foreground even when another app owns the foreground."""
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if user32.GetForegroundWindow() == hwnd:
        return
    current = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached: list[int] = []
    for thread_id in {foreground_thread, target_thread}:
        if thread_id and user32.AttachThreadInput(current, thread_id, True):
            attached.append(thread_id)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for thread_id in attached:
            user32.AttachThreadInput(current, thread_id, False)


def _root_hwnd(element) -> int:
    try:
        hwnd = element.element_info.handle
        return int(ctypes.windll.user32.GetAncestor(hwnd, 2))  # GA_ROOT
    except Exception:  # noqa: BLE001
        return 0

class WindowNotFound(Exception):
    """No top-level window matches the requested substring."""


class StaleElement(Exception):
    """The element id is unknown or the element no longer works."""


class StopRequested(Exception):
    def __init__(self, executed: int) -> None:
        super().__init__("stopped by hotkey")
        self.executed = executed


def _safe(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001 - COM raises many different errors
        return default


def _rect_list(element) -> list[int] | None:
    rect = _safe(element.rectangle)
    if rect is None:
        return None
    return [rect.left, rect.top, max(0, rect.right - rect.left), max(0, rect.bottom - rect.top)]


def _control_type(element) -> str:
    try:
        return str(element.element_info.control_type or "")
    except Exception:  # noqa: BLE001
        return ""


def _value(element) -> str | None:
    try:
        value = element.iface_value.Value()
        return str(value) if value is not None else None
    except Exception:  # noqa: BLE001
        return None


def _texts(element) -> str | None:
    try:
        parts = element.texts()
    except Exception:  # noqa: BLE001
        return None
    flat: list[str] = []
    for part in parts:
        if isinstance(part, list):
            flat.extend(str(item) for item in part if item)
        elif part:
            flat.append(str(part))
    text = "\n".join(flat)
    return text or None


def _trim(text: str | None, limit: int = 300) -> str | None:
    if text is None:
        return None
    return text[:limit]


class _Worker:
    """One COM-initialized thread that owns every pywinauto wrapper."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="pilot-uia", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            comtypes.CoInitialize()
        except Exception:  # noqa: BLE001
            logger.exception("CoInitialize failed")
        while True:
            item = self._queue.get()
            if item is None:
                break
            fn, result = item
            try:
                result["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - propagate to the caller
                result["error"] = exc
            finally:
                result["done"].set()

    def call(self, fn: Callable[[], Any], timeout: float = 60.0) -> Any:
        result: dict[str, Any] = {"done": threading.Event()}
        self._queue.put((fn, result))
        if not result["done"].wait(timeout):
            raise TimeoutError("UIA operation timed out")
        if "error" in result:
            raise result["error"]
        return result.get("value")


@dataclass
class ElementRef:
    element_id: int
    window: str
    wrapper: Any
    control_type: str
    name: str


class UiaController:
    def __init__(self) -> None:
        self._worker = _Worker()
        self._snapshot_id = 0
        self._elements: dict[int, ElementRef] = {}

    def observe(
        self,
        window: str | None = None,
        max_elements: int = MAX_ELEMENTS_DEFAULT,
        depth: int = MAX_DEPTH_DEFAULT,
    ) -> dict:
        return self._worker.call(
            lambda: self._observe(window, max_elements, depth), timeout=35.0
        )

    def act(self, steps: list[dict], stop_event: threading.Event) -> dict:
        return self._worker.call(
            lambda: self._act(steps, stop_event), timeout=180.0
        )

    def window_list(self) -> list[dict]:
        return self._worker.call(self._window_list, timeout=15.0)

    def window_rect(self, window: str | None) -> list[int] | None:
        return self._worker.call(lambda: self._window_rect(window), timeout=15.0)

    # -- worker-side implementation -------------------------------------

    def _window_list(self) -> list[dict]:
        desktop = Desktop(backend="uia")
        active = _active_window_title()
        windows = []
        for candidate in _safe(desktop.windows, []) or []:
            title = _safe(candidate.window_text, "") or ""
            if not title or title == "Program Manager":
                continue
            if not _safe(candidate.is_visible, True):
                continue
            windows.append(
                {
                    "title": title,
                    "class_name": _safe(candidate.class_name, "") or "",
                    "process_id": _safe(candidate.process_id),
                    "focused": title == active,
                }
            )
        return windows

    def _observe(self, window: str | None, max_elements: int, depth: int) -> dict:
        desktop = Desktop(backend="uia")
        visible: list[tuple[Any, str, str]] = []
        for candidate in _safe(desktop.windows, []) or []:
            title = _safe(candidate.window_text, "") or ""
            class_name = _safe(candidate.class_name, "") or ""
            if not title or title == "Program Manager":
                continue
            if not _safe(candidate.is_visible, True):
                continue
            visible.append((candidate, title, class_name))
        selected = [
            item
            for item in visible
            if window is None or _matches(window, item[1], item[2])
        ]
        if window is not None and not selected:
            raise WindowNotFound(f"window matching {window!r} not found")
        selected = selected[:6]

        self._snapshot_id += 1
        snapshot_id = self._snapshot_id
        self._elements.clear()
        budget = max(1, min(max_elements, 1000))
        elements: list[dict] = []
        windows: list[dict] = []
        for candidate, title, class_name in selected:
            windows.append(
                {
                    "title": title,
                    "class_name": class_name,
                    "process_id": _safe(candidate.process_id),
                    "rect": _rect_list(candidate),
                }
            )
            self._walk(candidate, title, 0, depth, budget, elements)
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "active_window": _active_window_title(),
            "windows": windows,
            "elements": elements,
        }

    def _walk(
        self,
        element,
        window_title: str,
        level: int,
        max_depth: int,
        budget: int,
        out: list[dict],
    ) -> None:
        if len(out) >= budget:
            return
        control_type = _control_type(element)
        name = _safe(element.window_text, "") or ""
        element_id = len(out) + 1
        info = {
            "id": element_id,
            "window": window_title,
            "control_type": control_type,
            "name": _trim(name),
            "automation_id": _safe(element.automation_id, "") or "",
            "class_name": _safe(element.class_name, "") or "",
            "rect": _rect_list(element),
            "enabled": bool(_safe(element.is_enabled, False)),
            "focused": bool(_safe(element.has_keyboard_focus, False)),
            "value": _trim(_value(element)),
            "text": _trim(_texts(element)),
        }
        self._elements[element_id] = ElementRef(
            element_id=element_id,
            window=window_title,
            wrapper=element,
            control_type=control_type,
            name=name,
        )
        out.append(info)
        if level >= max_depth:
            return
        for child in _safe(element.children, []) or []:
            self._walk(child, window_title, level + 1, max_depth, budget, out)
            if len(out) >= budget:
                return

    def _act(self, steps: list[dict], stop_event: threading.Event) -> dict:
        executed = 0
        results: list[dict] = []
        for step in steps:
            if stop_event.is_set():
                raise StopRequested(executed)
            self._run_step(step)
            executed += 1
            results.append({"ok": True})
        return {"ok": True, "executed": executed, "stopped": False, "results": results}

    def _run_step(self, step: dict) -> None:
        action = step.get("action")
        if action == "click":
            actions.click(self._element(step))
        elif action == "set_text":
            actions.set_text(self._element(step), str(step.get("text", "")))
        elif action == "type_text":
            actions.type_unicode(str(step.get("text", "")))
        elif action == "key":
            actions.send_keys(str(step.get("keys", "")))
        elif action == "focus":
            element = self._element(step)
            actions.focus(element)
            _force_foreground(_root_hwnd(element))
        elif action == "focus_window":
            self._focus_window(str(step.get("window", "")))
        elif action == "wait":
            time.sleep(max(0.0, min(float(step.get("seconds", 0.1)), 10.0)))
        else:
            raise actions.ActionError(f"unknown action: {action!r}")

    def _element(self, step: dict) -> ElementRef:
        try:
            element_id = int(step["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise actions.ActionError("action requires an integer 'id'") from exc
        ref = self._elements.get(element_id)
        if ref is None:
            raise StaleElement(
                f"element {element_id} is not in the last snapshot; call /observe first"
            )
        return ref.wrapper

    def _focus_window(self, window: str) -> None:
        desktop = Desktop(backend="uia")
        for candidate in _safe(desktop.windows, []) or []:
            title = _safe(candidate.window_text, "") or ""
            class_name = _safe(candidate.class_name, "") or ""
            if title and _matches(window, title, class_name):
                candidate.set_focus()
                _force_foreground(_root_hwnd(candidate))
                time.sleep(0.15)
                return
        raise WindowNotFound(f"window matching {window!r} not found")

    def _window_rect(self, window: str | None) -> list[int] | None:
        if window is None:
            return None
        desktop = Desktop(backend="uia")
        for candidate in _safe(desktop.windows, []) or []:
            title = _safe(candidate.window_text, "") or ""
            class_name = _safe(candidate.class_name, "") or ""
            if title and _matches(window, title, class_name):
                return _rect_list(candidate)
        raise WindowNotFound(f"window matching {window!r} not found")


def _matches(needle: str, title: str, class_name: str) -> bool:
    needle = needle.lower()
    return needle in title.lower() or needle in class_name.lower()


def _active_window_title() -> str:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buffer = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, 512)
        return buffer.value
    except Exception:  # noqa: BLE001
        return ""
