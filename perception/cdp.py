"""Read Chromium/Electron accessibility trees over CDP (no Playwright)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from websockets.sync.client import connect


class CdpError(RuntimeError):
    pass


@dataclass
class CdpTarget:
    title: str
    url: str
    websocket_url: str


def list_targets(host: str, port: int = 9222, timeout: float = 5.0) -> list[CdpTarget]:
    try:
        response = httpx.get(f"http://{host}:{port}/json/list", timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CdpError(f"cannot reach CDP at {host}:{port}: {exc}") from exc
    targets = []
    for item in response.json():
        if item.get("type") != "page" or not item.get("webSocketDebuggerUrl"):
            continue
        targets.append(
            CdpTarget(
                title=item.get("title", ""),
                url=item.get("url", ""),
                websocket_url=item["webSocketDebuggerUrl"].replace(
                    "ws://localhost", f"ws://{host}"
                ).replace("ws://127.0.0.1", f"ws://{host}"),
            )
        )
    return targets


def accessibility_nodes(target: CdpTarget, timeout: float = 15.0) -> list[dict]:
    request = {"id": 1, "method": "Accessibility.getFullAXTree"}
    try:
        with connect(target.websocket_url, open_timeout=timeout, max_size=64 * 1024 * 1024) as ws:
            ws.send(json.dumps(request))
            while True:
                message = json.loads(ws.recv(timeout=timeout))
                if message.get("id") == 1:
                    break
    except Exception as exc:  # noqa: BLE001 - websockets raises many transport errors
        raise CdpError(f"CDP request failed: {exc}") from exc
    if "error" in message:
        raise CdpError(f"CDP error: {message['error']}")
    nodes: list[dict] = []
    for index, node in enumerate(message.get("result", {}).get("nodes", []), start=1):
        if node.get("ignored"):
            continue
        role = node.get("role", {}).get("value")
        name = node.get("name", {}).get("value")
        value = node.get("value", {}).get("value")
        if isinstance(role, dict):
            role = role.get("value")
        nodes.append(
            {
                "id": index,
                "role": str(role or ""),
                "name": str(name or ""),
                "value": str(value) if isinstance(value, (str, int, float)) else "",
            }
        )
    return nodes


def snapshot(
    host: str, port: int = 9222, title_filter: str | None = None
) -> tuple[str, list[dict]]:
    targets = list_targets(host, port)
    if title_filter:
        targets = [t for t in targets if title_filter.lower() in t.title.lower()]
    if not targets:
        raise CdpError(f"no CDP page targets at {host}:{port}")
    target = targets[0]
    return target.title, accessibility_nodes(target)
