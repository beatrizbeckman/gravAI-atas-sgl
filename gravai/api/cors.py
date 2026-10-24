"""
CORS: which other web origins (the SGL) may call the API from a browser.

The /demo page is served by the API itself, so it never needs this; the SGL does
when its pages call the API directly. Only the listed origins are allowed, never
'*': the API records meetings and must not answer any site on the internet.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def parse_origins(value: str) -> list[str]:
    """'http://a, http://b/' -> ['http://a', 'http://b'] (an origin has no trailing slash)."""
    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


def add_cors(app: FastAPI, origins: str) -> None:
    allowed = parse_origins(origins)
    if not allowed:
        return
    if "*" in allowed:
        raise ValueError("CORS_ORIGINS must list the allowed origins, '*' is not accepted")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        # Lets the browser read the .docx file name sent by /minutes/jobs/{id}/download.
        expose_headers=["Content-Disposition"],
    )
