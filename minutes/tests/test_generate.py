import json
import os

import pytest

from minutes import generate as gen
from minutes.generate import MinutesError, generate_minutes, missing_header_fields, resolve_template, suggest_filename
from minutes.templates import load_template

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def dell():
    return _load("reuniao_dell.json")


@pytest.fixture
def filled_reply():
    """What a good model reply looks like for the Dell fixture (ids are stripped: the code numbers rows)."""
    minutes = _load("ata_dell_preenchida.json")["minutes"]
    for key in ("decisoes", "plano_acao"):
        for row in minutes[key]:
            row.pop("id", None)
    return json.dumps(minutes, ensure_ascii=False)


class RecordingLLM:
    """Stands in for minutes.llm.generate: returns the scripted replies in order and records every prompt."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_happy_path_writes_docx_and_reports_metrics(tmp_path, dell, filled_reply, monkeypatch):
    monkeypatch.setattr(gen.llm, "model_name", lambda: "test-model")
    fake = RecordingLLM(filled_reply)
    out = tmp_path / "ata.docx"
    stages = []

    result = generate_minutes("dell", dell["header"], dell["utterances"], str(out), progress=stages.append, call_llm=fake)

    assert out.exists() and out.stat().st_size > 0
    assert stages == ["generating", "rendering"]
    assert result.participants == ["Ana", "Bruno", "Carla", "Diego"]  # from the transcript, sorted
    assert result.parts == 1 and result.llm_calls == 1 and result.retries == 0
    assert result.utterances == len(dell["utterances"])
    assert result.llm_model == "test-model"
    assert result.minutes["plano_acao"][0]["id"] == "A1"
    assert result.header == dell["header"]  # all keys present, nothing added
    system, user = fake.calls[0]
    assert "Ata Dell" in system and "Portal de Suporte" in user


def test_participants_from_request_override_the_transcript(tmp_path, dell, filled_reply):
    result = generate_minutes(
        "dell", dell["header"], dell["utterances"], str(tmp_path / "a.docx"),
        participants=["Carla Souza (Dell)", " Ana ", ""], call_llm=RecordingLLM(filled_reply),
    )
    assert result.participants == ["Carla Souza (Dell)", "Ana"]


def test_header_defaults_and_unknown_keys(tmp_path):
    from minutes.llm import fake_generate

    prof = _load("reuniao_professores.json")
    header = {**prof["header"], "lixo": "x"}
    header.pop("tipo", None)
    result = generate_minutes("professores", header, prof["utterances"], str(tmp_path / "p.docx"), call_llm=fake_generate)
    assert result.header["tipo"] == "Orientação"  # template default
    assert "lixo" not in result.header


def test_missing_required_header_is_a_value_error(tmp_path, dell):
    with pytest.raises(ValueError, match="projeto"):
        generate_minutes("dell", {"data": "01/10/2026"}, dell["utterances"], str(tmp_path / "x.docx"), call_llm=RecordingLLM())
    assert missing_header_fields(load_template("dell"), {"projeto": " ", "data": "x"}) == ["projeto"]


def test_empty_transcript_is_reported(tmp_path, dell):
    bad = [{"speaker": "A", "start": 1, "end": 1, "text": "x"}, {"speaker": "B", "start": 0, "end": 2, "text": "   "}]
    with pytest.raises(MinutesError) as exc:
        generate_minutes("dell", dell["header"], bad, str(tmp_path / "x.docx"), call_llm=RecordingLLM())
    assert exc.value.code == "empty_transcript"


def test_bad_reply_is_retried_with_the_problem_appended(tmp_path, dell, filled_reply):
    fake = RecordingLLM("not json at all", '{"topicos": []}', filled_reply)
    result = generate_minutes("dell", dell["header"], dell["utterances"], str(tmp_path / "a.docx"), call_llm=fake)

    assert result.llm_calls == 3 and result.retries == 2
    first, second, third = (user for _, user in fake.calls)
    assert "rejeitada" not in first
    assert "rejeitada" in second and "not valid JSON" in second
    assert "rejeitada" in third and "topicos" in third and "required" in third


def test_retries_exhausted_become_llm_invalid_response(tmp_path, dell):
    fake = RecordingLLM("x", "y", "z")
    with pytest.raises(MinutesError) as exc:
        generate_minutes("dell", dell["header"], dell["utterances"], str(tmp_path / "a.docx"), retries=2, call_llm=fake)
    assert exc.value.code == "llm_invalid_response"
    assert "3 attempts" in exc.value.message and len(fake.calls) == 3


def test_llm_failures_become_llm_unreachable(tmp_path, dell):
    import requests

    for error in (RuntimeError("Could not reach Ollama"), requests.Timeout("slow")):
        with pytest.raises(MinutesError) as exc:
            generate_minutes("dell", dell["header"], dell["utterances"], str(tmp_path / "a.docx"), call_llm=RecordingLLM(error))
        assert exc.value.code == "llm_unreachable"


def test_long_transcript_is_split_and_merged(tmp_path, dell, filled_reply):
    partial = json.dumps({"topicos": [{"titulo": "Parte", "resumo": "..."}], "resumo": "parte"})
    fake = RecordingLLM(partial, partial, partial, filled_reply)

    result = generate_minutes("dell", dell["header"], dell["utterances"], str(tmp_path / "a.docx"), max_chars=1500, call_llm=fake)

    assert result.parts == 3 and result.llm_calls == 4
    assert len(result.partials) == 3
    users = [user for _, user in fake.calls]
    assert "parte 1 de 3" in users[0] and "parte 3 de 3" in users[2]
    assert "Consolide tudo" in users[3] and "Parte 3" in users[3]


def test_custom_template_goes_through_the_same_path(tmp_path, dell):
    custom = {"instructions": "Resuma a reunião em um parágrafo."}
    fake = RecordingLLM(json.dumps({"conteudo": "Reunião resumida."}))
    result = generate_minutes("custom", {"projeto": "X", "data": "01/10/2026"}, dell["utterances"], str(tmp_path / "c.docx"), custom=custom, call_llm=fake)
    assert result.template.id == "custom" and result.minutes == {"conteudo": "Reunião resumida."}


def test_resolve_template_rules():
    assert resolve_template("daily").id == "daily"
    with pytest.raises(ValueError, match="needs the 'custom' object"):
        resolve_template("custom")
    with pytest.raises(ValueError, match="only accepted with template 'custom'"):
        resolve_template("dell", {"instructions": "x"})
    with pytest.raises(FileNotFoundError, match="Available"):
        resolve_template("nope")


def test_fake_provider_fills_every_section(tmp_path, dell, monkeypatch):
    from minutes import llm

    monkeypatch.setattr(llm, "model_name", lambda: "fake")
    result = generate_minutes("dell", dell["header"], dell["utterances"], str(tmp_path / "f.docx"), call_llm=llm.fake_generate)
    assert set(result.minutes) == {s.key for s in load_template("dell").sections}
    assert result.minutes["plano_acao"][0]["status"] == "Pendente"
    assert "fake" in result.minutes["resumo"]


def test_suggest_filename_slugifies_the_project():
    import time

    when = time.strptime("2026-10-01", "%Y-%m-%d")
    assert suggest_filename("dell", {"projeto": "Portal de Suporte / Fase 2 — Ação"}, when) == "ata_dell_2026-10-01_portal-de-suporte-fase-2-acao.docx"
    assert suggest_filename("daily", {}, when) == "ata_daily_2026-10-01.docx"
