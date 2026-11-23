"""Unit tests for the bridge client (no network, MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from perception.bridge_client import BridgeClient, BridgeError, BridgeStopped


def make_client(handler) -> BridgeClient:
    return BridgeClient(
        "http://bridge.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )


def test_observe_sends_token_and_parses_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Pilot-Token"] == "secret"
        assert request.url.path == "/observe"
        body = json.loads(request.content)
        assert body["window"] == "Блокнот"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "snapshot_id": 3,
                "windows": [{"title": "Без имени — Блокнот"}],
                "elements": [{"id": 1, "control_type": "Edit", "value": "hi"}],
            },
        )

    with make_client(handler) as client:
        snapshot = client.observe(window="Блокнот")
    assert snapshot["snapshot_id"] == 3
    assert snapshot["elements"][0]["value"] == "hi"


def test_act_single_action_wraps_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"steps": [{"action": "wait", "seconds": 0.1}]}
        return httpx.Response(200, json={"ok": True, "executed": 1, "results": [{"ok": True}]})

    with make_client(handler) as client:
        result = client.act({"action": "wait", "seconds": 0.1})
    assert result["executed"] == 1


def test_stopped_series_raises_bridge_stopped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "ok": False,
                "stopped": True,
                "executed": 7,
                "error": "stopped by hotkey",
                "code": "stopped",
            },
        )

    with make_client(handler) as client:
        with pytest.raises(BridgeStopped) as info:
            client.act([{"action": "wait", "seconds": 1}])
    assert info.value.executed == 7


def test_missing_token_is_config_error() -> None:
    with pytest.raises(BridgeError) as info:
        BridgeClient("http://bridge.test", "")
    assert info.value.code == "config"


def test_http_error_payload_becomes_bridge_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"ok": False, "error": "window not found", "code": "window_not_found"},
        )

    with make_client(handler) as client:
        with pytest.raises(BridgeError) as info:
            client.observe(window="nope")
    assert info.value.code == "window_not_found"
    assert info.value.status == 404


def test_screenshot_returns_bytes() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"data"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/screenshot"
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    with make_client(handler) as client:
        assert client.screenshot() == png
