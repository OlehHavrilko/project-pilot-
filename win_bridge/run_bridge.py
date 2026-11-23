"""Entry point of the Windows bridge."""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from config import parse_args
from server import create_app


def _redirect_logs() -> None:
    log_file = os.environ.get("PILOT_BRIDGE_LOG")
    if not log_file:
        return
    stream = open(log_file, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
    sys.stdout = stream
    sys.stderr = stream


def main() -> int:
    _redirect_logs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    config = parse_args()
    app = create_app(config)
    logging.getLogger(__name__).info(
        "listening on http://%s:%s (hotkey %s)", config.host, config.port, config.hotkey
    )
    uvicorn.run(app, host=config.host, port=config.port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
