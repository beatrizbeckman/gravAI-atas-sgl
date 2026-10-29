import json
import time

import pytest
import requests

from gravai.minutes import generate as gen
from gravai.minutes import llm
from gravai.minutes.generate import (
    MinutesError,
    generate_minutes,
    missing_header_fields,
    prepare_utterances,
    resolve_template,
    suggest_filename,
)
from gravai.minutes.prompt_builder import split_transcript
from gravai.minutes.templates import load_template


@pytest.fixture
def filled_reply(filled_minutes):
    """What a good model reply looks like (ids are stripped: the code numbers the rows)."""
    for key in ("decisoes", "plano_acao"):
        for row in filled_minutes[key]:
            row.pop("id", None)
    return json.dumps(filled_minutes, ensure_ascii=False)


class RecordingLLM:
    """Stands in for minutes.llm.generate: returns the scripted replies in order and records every prompt."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_happy_path_writes_docx_and_reports_metrics(tmp_path, meeting, speakers, filled_reply, monkeypatch):
    monkeypatch.setattr(gen.llm, "model_name", lambda: "test-model")
    fake = RecordingLLM(filled_reply)
    out = tmp_path / "ata.docx"
    stages = []

    result = generate_minutes(
        "dell", meeting["header"], meeting["utterances"], str(out), progress=stages.append, call_llm=fake
    )

    assert out.exists() and out.stat().st_size > 0
    assert stages == ["generating", "rendering"]
    assert result.participants == speakers  # from the transcript, sorted
    assert result.parts == 1 and result.llm_calls == 1 and result.retries == 0
    assert result.utterances == len(meeting["utterances"])
    assert result.llm_model == "test-model"
    assert result.minutes["plano_acao"][0]["id"] == "A1"
    assert result.header == meeting["header"]  # all keys present, nothing added
    system, user = fake.calls[0]
    assert "Ata Dell" in system and meeting["header"]["projeto"] in user


def test_participants_from_request_override_the_transcript(tmp_path, short_meeting, filled_reply):
    result = generate_minutes(
        "dell",
        short_meeting["header"],
        short_meeting["utterances"],
        str(tmp_path / "a.docx"),
        participants=["Paula Souza (PM)", " Marina ", ""],
        call_llm=RecordingLLM(filled_reply),
    )
    assert result.participants == ["Paula Souza (PM)", "Marina"]


def test_header_defaults_and_unknown_keys(tmp_path, short_meeting):
    header = {"projeto": "GravAI Atas", "data": "02/03/2026", "professores": "Prof. Marcos", "lixo": "x"}
    result = generate_minutes(
        "professores", header, short_meeting["utterances"], str(tmp_path / "p.docx"), call_llm=llm.fake_generate
    )
    assert result.header["tipo"] == "Orientação"  # template default
    assert "lixo" not in result.header


def test_missing_required_header_is_a_value_error(tmp_path, short_meeting):
    with pytest.raises(ValueError, match="projeto"):
        generate_minutes(
            "dell",
            {"data": "01/10/2026"},
            short_meeting["utterances"],
            str(tmp_path / "x.docx"),
            call_llm=RecordingLLM(),
        )
    assert missing_header_fields(load_template("dell"), {"projeto": " ", "data": "x"}) == ["projeto"]


def test_empty_transcript_is_reported(tmp_path, meeting):
    bad = [{"speaker": "A", "start": 1, "end": 1, "text": "x"}, {"speaker": "B", "start": 0, "end": 2, "text": "   "}]
    with pytest.raises(MinutesError) as exc:
        generate_minutes("dell", meeting["header"], bad, str(tmp_path / "x.docx"), call_llm=RecordingLLM())
    assert exc.value.code == "empty_transcript"


def test_bad_reply_is_retried_with_the_problem_appended(tmp_path, short_meeting, filled_reply):
    fake = RecordingLLM("not json at all", '{"topicos": []}', filled_reply)
    result = generate_minutes(
        "dell", short_meeting["header"], short_meeting["utterances"], str(tmp_path / "a.docx"), call_llm=fake
    )

    assert result.llm_calls == 3 and result.retries == 2
    first, second, third = (user for _, user in fake.calls)
    assert "rejeitada" not in first
    assert "rejeitada" in second and "not valid JSON" in second
    assert "rejeitada" in third and "topicos" in third and "required" in third


def test_retries_exhausted_become_llm_invalid_response(tmp_path, short_meeting):
    fake = RecordingLLM("x", "y", "z")
    with pytest.raises(MinutesError) as exc:
        generate_minutes(
            "dell",
            short_meeting["header"],
            short_meeting["utterances"],
            str(tmp_path / "a.docx"),
            retries=2,
            call_llm=fake,
        )
    assert exc.value.code == "llm_invalid_response"
    assert "3 attempts" in exc.value.message and len(fake.calls) == 3


def test_llm_failures_become_llm_unreachable(tmp_path, short_meeting):
    for error in (RuntimeError("Could not reach Ollama"), requests.Timeout("slow")):
        with pytest.raises(MinutesError) as exc:
            generate_minutes(
                "dell",
                short_meeting["header"],
                short_meeting["utterances"],
                str(tmp_path / "a.docx"),
                call_llm=RecordingLLM(error),
            )
        assert exc.value.code == "llm_unreachable"


def test_long_transcript_is_split_and_merged(tmp_path, meeting, filled_reply):
    max_chars = 5000
    expected_parts = len(split_transcript(prepare_utterances(meeting["utterances"]), max_chars))
    assert expected_parts >= 2
    partial = json.dumps({"topicos": [{"titulo": "Parte", "resumo": "..."}], "resumo": "parte"})
    fake = RecordingLLM(*([partial] * expected_parts), filled_reply)

    result = generate_minutes(
        "dell", meeting["header"], meeting["utterances"], str(tmp_path / "a.docx"), max_chars=max_chars, call_llm=fake
    )

    assert result.parts == expected_parts and result.llm_calls == expected_parts + 1
    assert len(result.partials) == expected_parts
    users = [user for _, user in fake.calls]
    assert f"parte 1 de {expected_parts}" in users[0] and f"parte {expected_parts} de {expected_parts}" in users[-2]
    assert "Consolide tudo" in users[-1] and f"Parte {expected_parts}" in users[-1]


def test_custom_template_goes_through_the_same_path(tmp_path, short_meeting):
    custom = {"instructions": "Resuma a reunião em um parágrafo."}
    fake = RecordingLLM(json.dumps({"conteudo": "Reunião resumida."}))
    result = generate_minutes(
        "custom",
        {"projeto": "X", "data": "01/10/2026"},
        short_meeting["utterances"],
        str(tmp_path / "c.docx"),
        custom=custom,
        call_llm=fake,
    )
    assert result.template.id == "custom" and result.minutes == {"conteudo": "Reunião resumida."}


def test_resolve_template_rules():
    assert resolve_template("daily").id == "daily"
    with pytest.raises(ValueError, match="needs the 'custom' object"):
        resolve_template("custom")
    with pytest.raises(ValueError, match="only accepted with template 'custom'"):
        resolve_template("dell", {"instructions": "x"})
    with pytest.raises(FileNotFoundError, match="Available"):
        resolve_template("nope")


def test_fake_provider_fills_every_section(tmp_path, short_meeting, monkeypatch):
    monkeypatch.setattr(llm, "model_name", lambda: "fake")
    result = generate_minutes(
        "dell",
        short_meeting["header"],
        short_meeting["utterances"],
        str(tmp_path / "f.docx"),
        call_llm=llm.fake_generate,
    )
    assert set(result.minutes) == {s.key for s in load_template("dell").sections}
    assert result.minutes["plano_acao"][0]["status"] == "Pendente"
    assert "fake" in result.minutes["resumo"]


def test_suggest_filename_slugifies_the_project():
    when = time.strptime("2026-10-01", "%Y-%m-%d")
    assert (
        suggest_filename("dell", {"projeto": "Portal de Suporte / Fase 2 — Ação"}, when)
        == "ata_dell_2026-10-01_portal-de-suporte-fase-2-acao.docx"
    )
    assert suggest_filename("daily", {}, when) == "ata_daily_2026-10-01.docx"


def test_a_first_name_in_a_table_becomes_the_participants_full_name():
    from gravai.minutes.generate import full_participant_names
    from gravai.minutes.templates import load_template

    minutes = {
        "plano_acao": [
            {"acao": "Corrigir o formulário", "responsavel": "Beatriz", "prazo": "04/11"},
            {"acao": "Testar o cadastro", "responsavel": "Lucas", "prazo": "29/10"},  # not in the call: kept
            {"acao": "Revisar", "responsavel": "Ana", "prazo": "A definir"},  # two Anas: ambiguous, kept
            {"acao": "Atualizar", "responsavel": "beckman", "prazo": "A definir"},
        ],
        "decisoes": [{"decisao": "Beatriz", "aprovada_por": "Grupo"}],
    }
    people = ["Ana Beatriz Beckman", "Ana Souza"]

    out = full_participant_names(load_template("dell"), minutes, people)

    assert [r["responsavel"] for r in out["plano_acao"]] == [
        "Ana Beatriz Beckman",
        "Lucas",
        "Ana",
        "Ana Beatriz Beckman",
    ]
    assert out["plano_acao"][0]["acao"] == "Corrigir o formulário"
