import pytest
import requests

from gravai.minutes import llm


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


# ------------------------------------------------- openai-compatible provider

OPENAI_OK = {
    "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "choices": [{"message": {"role": "assistant", "content": '{"resumo": "ok"}'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
}
CFG = {"base_url": "https://api.deepinfra.com/v1/openai/", "api_key": "sk-test", "model": "m", "timeout": 30}


def test_openai_chat_request_shape_and_reply(monkeypatch):
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse(200, OPENAI_OK)

    monkeypatch.setattr(requests, "post", fake_post)
    reply = llm.openai_chat("sys", "usr", **CFG)

    assert reply.content == '{"resumo": "ok"}'
    assert reply.model == "meta-llama/Meta-Llama-3.1-8B-Instruct"
    assert reply.usage["total_tokens"] == 150
    assert reply.json_mode is True
    assert reply.finish_reason == "stop"
    assert reply.seconds >= 0
    # trailing slash in base_url must not produce a double slash
    assert sent["url"] == "https://api.deepinfra.com/v1/openai/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert sent["json"]["model"] == "m"
    assert sent["json"]["temperature"] == 0
    assert sent["json"]["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in sent["json"]["messages"]] == ["system", "user"]
    assert sent["timeout"] == 30


def test_openai_compatible_generate_returns_only_the_text(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(200, OPENAI_OK))
    assert llm.openai_compatible_generate("s", "u", **CFG) == '{"resumo": "ok"}'


@pytest.mark.parametrize(
    "error_text",
    [
        '{"error": "response_format is not supported for this model"}',
        '{"error":{"message":"Failed to validate JSON.","code":"json_validate_failed","failed_generation":""}}',
    ],
)
def test_openai_chat_retries_without_json_mode_when_provider_rejects_it(monkeypatch, error_text):
    payloads = []

    def fake_post(url, json, headers, timeout):
        payloads.append(json)
        if "response_format" in json:
            return FakeResponse(400, text=error_text)
        return FakeResponse(200, OPENAI_OK)

    monkeypatch.setattr(requests, "post", fake_post)
    reply = llm.openai_chat("s", "u", **CFG)

    assert reply.json_mode is False
    assert len(payloads) == 2
    assert "response_format" in payloads[0] and "response_format" not in payloads[1]


@pytest.mark.parametrize(
    "status, text, match",
    [
        (401, "unauthorized", "API key"),
        (403, "forbidden", "API key"),
        (402, "You need positive balance", "no balance"),
        (404, "not found", "does not serve model"),
        (400, '{"error": "unknown model m"}', "does not serve model"),
        (413, "Request too large", "too large"),
        (429, "slow down", "rate limiting"),
        (500, "boom", "LLM provider error 500"),
    ],
)
def test_openai_chat_http_errors_are_explained(monkeypatch, status, text, match):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(status, text=text))
    with pytest.raises(RuntimeError, match=match):
        llm.openai_chat("s", "u", **CFG)


def test_openai_chat_down_is_explained(monkeypatch):
    def fake_post(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="Could not reach"):
        llm.openai_chat("s", "u", **CFG)


def test_openai_chat_empty_reply_is_an_error(monkeypatch):
    body = {"choices": [{"message": {"content": "  "}}]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(200, body))
    with pytest.raises(RuntimeError, match="empty"):
        llm.openai_chat("s", "u", **CFG)


def test_openai_chat_refuses_to_run_without_a_key():
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        llm.openai_chat("s", "u", **{**CFG, "api_key": ""})


def test_generate_routes_to_openai_compatible(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("LLM_API_KEY", "gsk-test")
    monkeypatch.setenv("LLM_MODEL", "llama-3.1-8b-instant")
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, model=json["model"], max_tokens=json.get("max_tokens"))
        return FakeResponse(200, OPENAI_OK)

    monkeypatch.setattr(requests, "post", fake_post)
    assert llm.generate("s", "u") == '{"resumo": "ok"}'
    assert sent == {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.1-8b-instant",
        "max_tokens": 8000,
    }
    assert llm.model_name() == "llama-3.1-8b-instant"


def test_openai_chat_optional_max_tokens_and_extra(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        requests, "post", lambda url, json, headers, timeout: (sent.update(json), FakeResponse(200, OPENAI_OK))[1]
    )

    llm.openai_chat("s", "u", **CFG)
    assert "max_tokens" not in sent and "reasoning_effort" not in sent

    llm.openai_chat("s", "u", **CFG, max_tokens=8000, extra={"reasoning_effort": "low"})
    assert sent["max_tokens"] == 8000 and sent["reasoning_effort"] == "low"
