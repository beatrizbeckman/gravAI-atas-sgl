"""
The demonstration page: a single HTML file (api/static/demo.html) that talks
to the /minutes/* endpoints. It stands in for the SGL as reference client.
Also serves the dataset meetings (datasets/reunioes/) so the page can load a
real transcript with one click during a live demo.
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from gravai.minutes.dataset import describe_meeting, list_meetings, load_meeting

router = APIRouter(tags=["demo"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo_page() -> str:
    with open(os.path.join(STATIC_DIR, "demo.html"), encoding="utf-8") as f:
        return f.read()


@router.get("/demo/sgl", response_class=HTMLResponse, include_in_schema=False)
def sgl_page() -> str:
    """The "Reuniões" tab as it would look inside the SGL (same daisyUI theme), driving the real API."""
    with open(os.path.join(STATIC_DIR, "sgl.html"), encoding="utf-8") as f:
        return f.read()


@router.get("/demo/examples")
def list_examples() -> dict:
    examples = [
        {"id": meeting_id, "label": describe_meeting(load_meeting(meeting_id))} for meeting_id in list_meetings()
    ]
    return {"examples": examples}


@router.get("/demo/examples/{meeting_id}")
def get_example(meeting_id: str) -> dict:
    try:
        data = load_meeting(meeting_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"unknown example '{meeting_id}'") from exc
    return {"template": data["template"], "header": data["header"], "utterances": data["utterances"]}
