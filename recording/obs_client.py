"""Thin wrapper around obs-websocket for recording control."""

from __future__ import annotations

import os

import obsws_python as obs

DEFAULT_PORT = 4455
RECORDING_TRACK_MASK = 7  # tracks 1, 2 and 3


class ObsError(RuntimeError):
    pass


class ObsClient:
    def __init__(self, client: obs.ReqClient, host: str, port: int) -> None:
        self._client = client
        self.host = host
        self.port = port

    @classmethod
    def connect(
        cls,
        host: str | None = None,
        port: int = DEFAULT_PORT,
        password: str | None = None,
        timeout: float = 5.0,
    ) -> ObsClient:
        if host is None:
            host = os.environ.get("OBS_WS_HOST") or _gateway()
        if password is None:
            password = _read_password()
        try:
            client = obs.ReqClient(host=host, port=port, password=password, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - obsws has its own error types
            raise ObsError(f"cannot connect to OBS at {host}:{port}: {exc}") from exc
        return cls(client, host, port)

    def close(self) -> None:
        self._client.disconnect()

    # -- info -------------------------------------------------------------

    def version(self) -> str:
        return self._client.get_version().obs_version

    def recording(self) -> bool:
        return bool(self._client.get_record_status().output_active)

    def recording_dir_windows(self) -> str:
        return self._client.get_profile_parameter("AdvOut", "RecFilePath").parameter_value

    def audio_inputs(self) -> dict[str, dict[str, bool]]:
        result: dict[str, dict[str, bool]] = {}
        for item in self._client.get_input_list().inputs:
            name = item["inputName"]
            kind = item.get("inputKind", "")
            if "audio" not in kind and "wasapi" not in kind and "monitor" in kind:
                continue  # video-only inputs reject audio track requests
            try:
                tracks = self._client.get_input_audio_tracks(name).input_audio_tracks
            except Exception:  # noqa: BLE001 - not every source exposes audio
                continue
            result[name] = tracks
        return result

    def input_device(self, name: str) -> str:
        return self._client.get_input_settings(name).input_settings.get("device_id", "")

    def muted(self, name: str) -> bool:
        return bool(self._client.get_input_mute(name).input_muted)

    # -- changes ----------------------------------------------------------

    def enable_recording_tracks(self, mask: int = RECORDING_TRACK_MASK) -> int:
        self._client.set_profile_parameter("AdvOut", "RecTracks", str(mask))
        return int(self._client.get_profile_parameter("AdvOut", "RecTracks").parameter_value)

    def set_input_tracks(self, name: str, tracks: set[int]) -> None:
        values = {str(index): index in tracks for index in range(1, 7)}
        self._client.set_input_audio_tracks(name, values)

    def unmute(self, name: str) -> None:
        if self.muted(name):
            self._client.set_input_mute(name, False)

    def start_recording(self) -> None:
        self._client.start_record()

    def stop_recording(self) -> None:
        self._client.stop_record()


def _gateway() -> str:
    import subprocess

    output = subprocess.run(
        ["ip", "route", "show", "default"], capture_output=True, text=True, check=False
    ).stdout
    for line in output.splitlines():
        parts = line.split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
    return "127.0.0.1"


def _read_password() -> str:
    from perception.bridge_client import read_dotenv

    password = os.environ.get("OBS_WS_PASSWORD") or read_dotenv().get("OBS_WS_PASSWORD")
    if not password:
        raise ObsError("OBS_WS_PASSWORD is not set (env or .env)")
    return password
