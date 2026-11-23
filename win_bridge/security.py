"""Token authentication for the bridge HTTP API."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

TOKEN_HEADER = "X-Pilot-Token"


def make_token_checker(expected: str):
    """Return a FastAPI dependency that verifies the shared bridge token."""

    def check(x_pilot_token: str | None = Header(default=None, alias=TOKEN_HEADER)) -> None:
        if not x_pilot_token:
            raise HTTPException(status_code=401, detail="missing bridge token")
        if not hmac.compare_digest(x_pilot_token, expected):
            raise HTTPException(status_code=403, detail="invalid bridge token")

    return check
