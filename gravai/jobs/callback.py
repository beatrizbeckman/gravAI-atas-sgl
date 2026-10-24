"""
Webhook: when a job that came with a callback_url finishes (done or failed), the
API POSTs the public job object there, so the client (the SGL) does not need to
poll for meetings that last hours. The call carries the API_KEY in X-API-Key, so
the receiver can tell it came from this API.

Delivery runs in its own thread: a slow or offline receiver never holds up the
next job. Three attempts; after that the client still has GET /minutes/jobs/{id}.
"""

import threading
import time

import requests

from gravai.config import Settings

ATTEMPTS = 3
WAIT_BETWEEN_SECONDS = (2, 10)
TIMEOUT_SECONDS = 10


def deliver(url: str, payload: dict) -> bool:
    """POSTs payload to url until a 2xx answer or ATTEMPTS failures. True when delivered."""
    headers = {}
    if key := Settings().API_KEY:
        headers["X-API-Key"] = key
    for attempt in range(ATTEMPTS):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
            if 200 <= response.status_code < 300:
                return True
            problem = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            problem = f"{exc.__class__.__name__}: {exc}"
        print(f"[callback] job {payload.get('id')} -> {url}: attempt {attempt + 1}/{ATTEMPTS} failed ({problem})")
        if attempt < ATTEMPTS - 1:
            time.sleep(WAIT_BETWEEN_SECONDS[attempt])
    return False


def deliver_in_background(url: str, payload: dict) -> None:
    threading.Thread(target=deliver, args=(url, payload), name="minutes-callback", daemon=True).start()
