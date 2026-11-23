"""HTTP client for the Windows bridge (runs in WSL)."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_TOKEN_HEADER = "X-Pilot-Token"


class BridgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        code: str | None = None,
        status: int | None = None,
        payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.payload = payload or {}


class BridgeStopped(BridgeError):
    """The bridge aborted an action series because the stop hotkey was pressed."""

    def __init__(self, message: str, executed: int) -> None:
        super().__init__(message, code="stopped", status=409)
        self.executed = executed


def read_dotenv(path: Path | None = None) -> dict[str, str]:
    path = path or Path(__file__).resolve().parents[1] / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def windows_host() -> str:
    """Address of the Windows side from WSL (gateway in NAT mode)."""
    try:
        output = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
        for line in output.splitlines():
            parts = line.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except Exception:  # noqa: BLE001 - discovery falls back to localhost
        logger.debug("cannot read default gateway", exc_info=True)
    return "127.0.0.1"


class BridgeClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 40.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise BridgeError("bridge token is empty", code="config")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={DEFAULT_TOKEN_HEADER: token},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BridgeClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @classmethod
    def discover(
        cls,
        token: str | None = None,
        port: int | None = None,
        timeout: float = 3.0,
    ) -> BridgeClient:
        dotenv = read_dotenv()
        token = token or os.environ.get("PILOT_BRIDGE_TOKEN") or dotenv.get(
            "PILOT_BRIDGE_TOKEN", ""
        )
        if not token:
            raise BridgeError(
                "PILOT_BRIDGE_TOKEN is not set (env or .env)", code="config"
            )
        port = port or int(os.environ.get("PILOT_BRIDGE_PORT", DEFAULT_PORT))
        explicit = os.environ.get("PILOT_BRIDGE_URL")
        candidates = [explicit] if explicit else []
        candidates += [f"http://127.0.0.1:{port}", f"http://{windows_host()}:{port}"]
        seen: set[str] = set()
        for base_url in candidates:
            if base_url in seen:
                continue
            seen.add(base_url)
            client = cls(base_url, token, timeout=timeout)
            try:
                health = client.health()
            except (BridgeError, httpx.HTTPError):
                client.close()
                continue
            if health.get("ok"):
                logger.info("bridge found at %s", base_url)
                return client
            client.close()
        raise BridgeError(
            "bridge is not reachable; run scripts/deploy_bridge.ps1", code="unreachable"
        )

    # -- endpoints ---------------------------------------------------------

    def health(self) -> dict:
        return self._request("GET", "/health")

    def status(self) -> dict:
        return self._request("GET", "/status")

    def observe(
        self, window: str | None = None, max_elements: int = 200, depth: int = 6
    ) -> dict:
        body = {"max_elements": max_elements, "depth": depth}
        if window:
            body["window"] = window
        return self._request("POST", "/observe", json=body)

    def act(self, steps: list[dict] | dict) -> dict:
        payload = {"steps": [steps]} if isinstance(steps, dict) else {"steps": steps}
        return self._request("POST", "/act", json=payload)

    def screenshot(self, window: str | None = None) -> bytes:
        params = {"window": window} if window else None
        response = self._client.get("/screenshot", params=params)
        if response.status_code != 200:
            self._raise_for(response)
        return response.content

    def play(self, pcm_base64: str, sample_rate: int = 24000, channels: int = 1) -> dict:
        return self._request(
            "POST",
            "/play",
            json={"pcm_base64": pcm_base64, "sample_rate": sample_rate, "channels": channels},
        )

    def watch_events(self, seconds: float = 5.0) -> list[dict]:
        """Collect bridge events (window open/close/focus) for a short window."""
        import json
        from urllib.parse import quote

        from websockets.sync.client import connect

        ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        url = f"{ws_base}/events?token={quote(self._token)}"
        events: list[dict] = []
        deadline = time.monotonic() + seconds
        with connect(url, open_timeout=5.0, max_size=8 * 1024 * 1024) as ws:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = ws.recv(timeout=remaining)
                except TimeoutError:
                    break
                try:
                    events.append(json.loads(raw))
                except ValueError:
                    continue
        return events

    def stop(self) -> dict:
        return self._request("POST", "/stop")

    def resume(self) -> dict:
        return self._request("POST", "/resume")

    # -- internals ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BridgeError(f"bridge request failed: {exc}", code="unreachable") from exc
        if response.status_code != 200:
            self._raise_for(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise BridgeError("bridge returned invalid JSON", code="protocol") from exc
        if not data.get("ok", False):
            raise BridgeError(
                data.get("error", "bridge error"),
                code=data.get("code"),
                status=response.status_code,
                payload=data,
            )
        return data

    def _raise_for(self, response: httpx.Response) -> None:
        try:
            data = response.json()
        except ValueError:
            data = {}
        message = data.get("error") or f"HTTP {response.status_code}"
        if data.get("code") == "stopped":
            raise BridgeStopped(message, executed=int(data.get("executed", 0)))
        raise BridgeError(
            message,
            code=data.get("code"),
            status=response.status_code,
            payload=data,
        )
