import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gravai.api.demo import router as demo_router
from gravai.api.minutes import router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    app = FastAPI()
    app.include_router(router)
    app.include_router(demo_router)
    return TestClient(app)


def test_minutes_routes_need_the_key_when_it_is_set(client):
    assert client.get("/minutes/templates").status_code == 401
    wrong = client.get("/minutes/templates", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401 and "X-API-Key" in wrong.json()["detail"]
    assert client.get("/minutes/templates", headers={"X-API-Key": "s3cret"}).status_code == 200
    # Validation never runs before the key check: a bad body without key is still 401.
    assert client.post("/minutes/from-transcript", json={}).status_code == 401


def test_demo_page_stays_open_so_it_can_ask_for_the_key(client):
    assert client.get("/demo").status_code == 200
    assert "X-API-Key" in client.get("/demo").text


def test_no_key_configured_means_open_api(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/minutes/templates").status_code == 200
