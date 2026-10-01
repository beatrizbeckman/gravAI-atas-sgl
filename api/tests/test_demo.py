from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.demo import router


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_demo_page_is_served_and_talks_to_the_minutes_api():
    response = client().get("/demo")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "GravAI" in html
    for path in ("/minutes/templates", "/minutes/from-transcript", "/minutes/from-recording", "/minutes/record-and-generate", "/minutes/jobs"):
        assert path in html


def test_examples_are_served_in_the_from_transcript_format():
    c = client()
    listed = c.get("/demo/examples").json()["examples"]
    assert [e["id"] for e in listed] == ["reuniao_dell", "reuniao_professores", "daily"]
    example = c.get("/demo/examples/reuniao_dell").json()
    assert example["template"] == "dell" and example["header"]["projeto"] and len(example["utterances"]) > 10
    assert set(example["utterances"][0]) == {"speaker", "start", "end", "text"}
    assert c.get("/demo/examples/nope").status_code == 404
