from fastapi import FastAPI
from fastapi.testclient import TestClient

from gravai.api.demo import router
from gravai.minutes.dataset import list_meetings


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_demo_page_is_served_and_talks_to_the_minutes_api():
    response = client().get("/demo")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "GravAI" in html
    for path in (
        "/minutes/templates",
        "/minutes/from-transcript",
        "/minutes/from-recording",
        "/minutes/record-and-generate",
        "/minutes/jobs",
    ):
        assert path in html


def test_examples_are_the_dataset_meetings_in_the_from_transcript_format():
    c = client()
    listed = c.get("/demo/examples").json()["examples"]
    assert [e["id"] for e in listed] == list_meetings()
    assert "ES2004a" in [e["id"] for e in listed]
    assert all("falas" in e["label"] for e in listed)

    example = c.get("/demo/examples/ES2004a").json()
    assert example["template"] == "dell" and example["header"]["projeto"] and len(example["utterances"]) > 10
    assert set(example["utterances"][0]) == {"speaker", "start", "end", "text"}
    assert c.get("/demo/examples/nope").status_code == 404


def test_sgl_tab_page_is_served_and_uses_the_integration_routes():
    response = client().get("/demo/sgl")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    html = response.text
    assert 'data-theme="business"' in html  # the SGL dark theme
    for path in (
        "/minutes/templates",
        "/minutes/templates/draft",
        "/minutes/record-and-generate",
        "/minutes/jobs?project_id=",
        "/stop",
        "/download",  # "Ver ata" and "Word" both use the .docx; the page no longer reads /result
        "X-API-Key",
    ):
        assert path in html
