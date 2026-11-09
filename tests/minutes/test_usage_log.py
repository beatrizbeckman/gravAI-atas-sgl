import csv
import json

import pytest
import requests

from gravai.minutes import generate as gen
from gravai.minutes import llm, usage_log


@pytest.fixture
def filled_reply(filled_minutes):
    for key in ("decisoes", "plano_acao"):
        for row in filled_minutes[key]:
            row.pop("id", None)
    return json.dumps(filled_minutes, ensure_ascii=False)


def reply(content, prompt=None, completion=None, reasoning=None):
    usage = {}
    if prompt is not None:
        usage = {"prompt_tokens": prompt, "completion_tokens": completion}
        if reasoning is not None:
            usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    return llm.ChatReply(content=content, model="m", seconds=1.5, usage=usage)


def test_usage_adds_the_provider_numbers_of_every_call():
    usage = gen.LLMUsage()
    assert usage.add("s", "u", reply("a", 1000, 200, 50)) == "a"
    usage.add("s", "u", reply("b", 3000, 500))

    assert (usage.prompt_tokens, usage.completion_tokens, usage.reasoning_tokens) == (4000, 700, 50)
    assert usage.total_tokens == 4700
    assert usage.largest_call_tokens == 3500
    assert usage.largest_prompt_tokens == 3000
    assert usage.estimated is False
    assert [c["seconds"] for c in usage.calls] == [1.5, 1.5]


def test_usage_is_estimated_from_characters_when_the_provider_says_nothing():
    usage = gen.LLMUsage()
    usage.add("s" * 40, "u" * 360, "r" * 80)  # plain text reply: fake provider or an old call_llm

    assert (usage.prompt_tokens, usage.completion_tokens) == (100, 20)
    assert usage.estimated is True


def test_generation_reports_usage_and_meeting_size(tmp_path, meeting, filled_reply, monkeypatch):
    monkeypatch.setattr(gen.llm, "model_name", lambda: "test-model")
    result = gen.generate_minutes(
        meeting["template"],
        meeting["header"],
        meeting["utterances"],
        str(tmp_path / "ata.docx"),
        call_llm=lambda system, user: reply(filled_reply, 5000, 900, 300),
        max_chars=24_000,
    )

    assert result.usage.total_tokens == 5900
    assert result.usage.reasoning_tokens == 300
    assert result.meeting_minutes > 0
    assert result.transcript_chars > 0


def test_generate_reply_keeps_the_usage_of_the_online_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", "gsk-test")
    body = {
        "model": "openai/gpt-oss-120b",
        "choices": [{"message": {"content": '{"resumo": "ok"}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 7770, "completion_tokens": 1519, "total_tokens": 9289},
    }

    class Ok:
        status_code, text = 200, ""

        def json(self):
            return body

    monkeypatch.setattr(requests, "post", lambda *a, **k: Ok())
    assert llm.generate_reply("s", "u").usage["prompt_tokens"] == 7770


def test_ollama_counts_become_usage(monkeypatch):
    class Ok:
        status_code = 200

        def json(self):
            return {"message": {"content": "{}"}, "prompt_eval_count": 120, "eval_count": 30}

    monkeypatch.setattr(requests, "post", lambda *a, **k: Ok())
    got = llm.ollama_chat("s", "u", host="http://x", model="m", num_ctx=1, timeout=1)
    assert got.usage == {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}


@pytest.fixture
def result(tmp_path, meeting, filled_reply, monkeypatch):
    monkeypatch.setattr(gen.llm, "model_name", lambda: "test-model")
    return gen.generate_minutes(
        meeting["template"],
        meeting["header"],
        meeting["utterances"],
        str(tmp_path / "ata.docx"),
        call_llm=lambda system, user: reply(filled_reply, 5000, 900),
        max_chars=24_000,
    )


def test_log_generation_appends_one_csv_row_per_meeting_and_prints_a_report(tmp_path, result, capsys):
    path = tmp_path / "usage" / "llm_usage.csv"
    usage_log.log_generation(result, job_id="abcdef123456", kind="from_transcript", project_id="p1", path=str(path))
    usage_log.log_generation(result, job_id="second", kind="from_transcript", path=str(path))

    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["job_id"] for r in rows] == ["abcdef123456", "second"]
    assert rows[0]["total_tokens"] == "5900"
    assert rows[0]["project_id"] == "p1"
    assert rows[0]["tokens_estimated"] == "False"
    assert int(rows[0]["tokens_per_meeting_hour"]) > 0

    out = capsys.readouterr().out
    assert "LLM usage · job abcdef12" in out
    assert "total 5.900" in out
    assert str(path) in out


def test_a_csv_that_cannot_be_written_does_not_fail_the_generation(tmp_path, result, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    usage_log.log_generation(result, path=str(blocker / "llm_usage.csv"))  # parent is a file
    assert "could not write the usage CSV" in capsys.readouterr().out


def test_tokens_per_hour():
    assert usage_log.tokens_per_hour(10_000, 30) == 20_000
    assert usage_log.tokens_per_hour(10_000, 0) is None
