"""
The demonstration page: a single HTML file (api/static/demo.html) that talks
to the /minutes/* endpoints. It stands in for the SGL as reference client.
Also serves the transcript fixtures so the page can load an example with one
click during a live demo.
"""
import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["demo"])

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "minutes", "tests", "fixtures")
EXAMPLES = {
    "reuniao_dell": "Reunião com a Dell (4 pessoas, 35 falas)",
    "reuniao_professores": "Reunião com professores",
    "daily": "Daily do time",
}


@router.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def demo_page() -> str:
    with open(os.path.join(STATIC_DIR, "demo.html"), encoding="utf-8") as f:
        return f.read()


@router.get("/demo/examples")
def list_examples() -> dict:
    return {"examples": [{"id": k, "label": v} for k, v in EXAMPLES.items()]}


@router.get("/demo/examples/{name}")
def get_example(name: str) -> dict:
    if name not in EXAMPLES:
        raise HTTPException(status_code=404, detail=f"unknown example '{name}'")
    with open(os.path.join(FIXTURES_DIR, f"{name}.json"), encoding="utf-8") as f:
        data = json.load(f)
    return {"template": data["template"], "header": data["header"], "utterances": data["utterances"]}
