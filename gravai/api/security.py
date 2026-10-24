"""
Shared-secret access to the API: when API_KEY is set, every call to /minutes/*
and to the recording endpoints must send it in the X-API-Key header. The SGL
keeps the key on its server; the /demo page asks for it once and keeps it in the
browser tab. Empty API_KEY (the default) leaves the API open, as before.
"""

import secrets

from fastapi import Header, HTTPException

from gravai.config import Settings

API_KEY_HEADER = "X-API-Key"


def require_api_key(x_api_key: str | None = Header(None, alias=API_KEY_HEADER)) -> None:
    expected = Settings().API_KEY
    if not expected:
        return
    # compare_digest takes the same time whatever the difference, so the key cannot be guessed by timing.
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail=f"missing or wrong {API_KEY_HEADER} header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
