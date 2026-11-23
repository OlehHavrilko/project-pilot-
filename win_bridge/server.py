"""Pilot Windows bridge: a thin, dumb HTTP service for UIA, screenshots and audio.

The bridge contains no decision logic and no model/API keys. Every request must
carry the shared token; the global stop hotkey aborts action series even if the
WSL side is hung.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from actions import ActionError
from audio import AudioPlayer
from config import BridgeConfig
from hotkey import HotkeyListener
from screenshot import capture_png
from security import make_token_checker
from uia import StaleElement, StopRequested, UiaController, WindowNotFound

logger = logging.getLogger(__name__)

API_VERSION = "1"


def _error(status_code: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": message, "code": code},
    )


def create_app(config: BridgeConfig) -> FastAPI:
    controller = UiaController()
    stop_event = threading.Event()
    audio = AudioPlayer(config.audio_device)
    started_at = time.monotonic()
    hotkey = HotkeyListener(config.hotkey, on_trigger=stop_event.set)
    auth = make_token_checker(config.token)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        ok = hotkey.start()
        logger.info("bridge started, hotkey registered: %s", ok)
        yield
        hotkey.stop()

    app = FastAPI(title="Pilot bridge", version=API_VERSION, lifespan=lifespan)
    app.state.hotkey = hotkey
    app.state.stop_event = stop_event

    @app.get("/health")
    def health(_: None = Depends(auth)) -> dict:
        return {"ok": True, "version": API_VERSION}

    @app.get("/status")
    def status(_: None = Depends(auth)) -> dict:
        return {
            "ok": True,
            "version": API_VERSION,
            "stopped": stop_event.is_set(),
            "hotkey": config.hotkey,
            "hotkey_registered": hotkey.registered,
            "host": config.host,
            "port": config.port,
            "uptime_s": round(time.monotonic() - started_at, 1),
            "audio_device": config.audio_device,
            "audio_available": audio.available,
        }

    @app.post("/observe")
    async def observe(request: Request, _: None = Depends(auth)) -> Response:
        body = await _json_body(request)
        try:
            snapshot = controller.observe(
                window=body.get("window"),
                max_elements=int(body.get("max_elements", 200)),
                depth=int(body.get("depth", 6)),
            )
        except WindowNotFound as exc:
            return _error(404, str(exc), "window_not_found")
        except TimeoutError as exc:
            return _error(504, str(exc), "timeout")
        return JSONResponse(content=snapshot)

    @app.post("/act")
    async def act(request: Request, _: None = Depends(auth)) -> Response:
        if stop_event.is_set():
            return _error(409, "stopped by hotkey", "stopped")
        body = await _json_body(request)
        steps = body.get("steps")
        if steps is None:
            steps = [{key: value for key, value in body.items() if key != "steps"}]
        if not isinstance(steps, list) or not steps:
            return _error(400, "'steps' must be a non-empty list", "bad_request")
        try:
            result = controller.act(steps, stop_event)
        except StopRequested as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "stopped": True,
                    "executed": exc.executed,
                    "error": "stopped by hotkey",
                    "code": "stopped",
                },
            )
        except StaleElement as exc:
            return _error(409, str(exc), "stale_element")
        except WindowNotFound as exc:
            return _error(404, str(exc), "window_not_found")
        except ActionError as exc:
            return _error(400, str(exc), "action_error")
        except TimeoutError as exc:
            return _error(504, str(exc), "timeout")
        return JSONResponse(content=result)

    @app.get("/screenshot")
    def screenshot(
        window: str | None = Query(default=None), _: None = Depends(auth)
    ) -> Response:
        try:
            rect = controller.window_rect(window)
        except WindowNotFound as exc:
            return _error(404, str(exc), "window_not_found")
        except TimeoutError as exc:
            return _error(504, str(exc), "timeout")
        png = capture_png(rect)
        headers = {"X-Rect": json.dumps(rect)}
        return Response(content=png, media_type="image/png", headers=headers)

    @app.post("/stop")
    def stop(_: None = Depends(auth)) -> dict:
        stop_event.set()
        return {"ok": True, "stopped": True}

    @app.post("/resume")
    def resume(_: None = Depends(auth)) -> dict:
        stop_event.clear()
        return {"ok": True, "stopped": False}

    @app.post("/play")
    async def play(request: Request, _: None = Depends(auth)) -> Response:
        body = await _json_body(request)
        pcm = body.get("pcm_base64")
        if not pcm:
            return _error(400, "'pcm_base64' is required", "bad_request")
        try:
            base64.b64decode(pcm, validate=True)
        except Exception:
            return _error(400, "'pcm_base64' is not valid base64", "bad_request")
        try:
            audio.play_pcm(
                pcm,
                sample_rate=int(body.get("sample_rate", 24000)),
                channels=int(body.get("channels", 1)),
            )
        except Exception as exc:  # noqa: BLE001 - device may be missing
            logger.exception("audio playback failed")
            return _error(503, f"audio playback failed: {exc}", "audio_unavailable")
        return JSONResponse(content={"ok": True})

    return app


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}
