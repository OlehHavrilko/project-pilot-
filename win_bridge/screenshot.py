"""Screen and window capture with mss."""

from __future__ import annotations

import mss
import mss.tools


def capture_png(rect: list[int] | None = None) -> bytes:
    """Capture the whole screen or ``rect`` = [left, top, width, height]."""
    with mss.mss() as sct:
        if rect is None:
            monitor = sct.monitors[0]
        else:
            left, top, width, height = rect
            monitor = {"left": left, "top": top, "width": width, "height": height}
        shot = sct.grab(monitor)
        return mss.tools.to_png(shot.rgb, shot.size)
