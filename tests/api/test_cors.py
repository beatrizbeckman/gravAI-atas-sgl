import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gravai.api.cors import add_cors, parse_origins
from gravai.api.minutes import router


def client(origins: str) -> TestClient:
    app = FastAPI()
    add_cors(app, origins)
    app.include_router(router)
    return TestClient(app)


def test_parse_origins_trims_spaces_slashes_and_empty_items():
    assert parse_origins(" http://sgl.lab/ , ,http://localhost:8080") == ["http://sgl.lab", "http://localhost:8080"]
    assert parse_origins("") == []


def test_listed_origin_is_allowed_including_the_preflight():
    c = client("http://sgl.lab")
    response = c.get("/minutes/templates", headers={"Origin": "http://sgl.lab"})
    assert response.headers["access-control-allow-origin"] == "http://sgl.lab"

    # The browser asks first (OPTIONS) before a POST with a JSON body.
    preflight = c.options(
        "/minutes/from-transcript",
        headers={
            "Origin": "http://sgl.lab",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://sgl.lab"


def test_other_origins_and_the_default_get_no_cors_headers():
    listed = client("http://sgl.lab").get("/minutes/templates", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in listed.headers
    default = client("").get("/minutes/templates", headers={"Origin": "http://sgl.lab"})
    assert default.status_code == 200 and "access-control-allow-origin" not in default.headers


def test_wildcard_is_refused():
    with pytest.raises(ValueError, match="not accepted"):
        add_cors(FastAPI(), "http://sgl.lab, *")
