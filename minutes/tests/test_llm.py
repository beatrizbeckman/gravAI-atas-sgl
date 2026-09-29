import pytest
import requests

from minutes import llm


class FakeResponse:
    def __init__(self, status_code, body=None, text=""):
        self.status_code, self._body, self.text = status_code, body or {}, text

    def json(self):
        return self._body


def test_ollama_request_shape_and_reply(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, json=json, timeout=timeout)
        return FakeResponse(200, {"message": {"role": "assistant", "content": '{"resumo": "ok"}'}})

    monkeypatch.setattr(requests, "post", fake_post)
    reply = llm.ollama_generate("sys", "usr", host="http://ollama:11434", model="m", num_ctx=4096, timeout=30)

    assert reply == '{"resumo": "ok"}'
    assert sent["url"] == "http://ollama:11434/api/chat"
    assert sent["json"]["model"] == "m"
    assert sent["json"]["format"] == "json"
    assert sent["json"]["stream"] is False
    assert sent["json"]["options"] == {"temperature": 0, "num_ctx": 4096}
    assert [m["role"] for m in sent["json"]["messages"]] == ["system", "user"]


@pytest.mark.parametrize("status, match", [(404, "ollama pull"), (500, "Ollama error 500")])
def test_ollama_http_errors_are_explained(monkeypatch, status, match):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(status, text="boom"))
    with pytest.raises(RuntimeError, match=match):
        llm.ollama_generate("s", "u", host="http://x", model="m", num_ctx=1, timeout=1)


def test_ollama_down_is_explained(monkeypatch):
    def fake_post(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="Is it running"):
        llm.ollama_generate("s", "u", host="http://x", model="m", num_ctx=1, timeout=1)


def test_ollama_empty_reply_is_an_error(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(200, {"message": {"content": "  "}}))
    with pytest.raises(RuntimeError, match="empty"):
        llm.ollama_generate("s", "u", host="http://x", model="m", num_ctx=1, timeout=1)
