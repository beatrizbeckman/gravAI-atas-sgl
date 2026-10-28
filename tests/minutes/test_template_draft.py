import json

import pytest

from gravai.minutes import template_draft
from gravai.minutes.custom_template import CustomSpec
from gravai.minutes.generate import MinutesError
from gravai.minutes.template_draft import build_draft_prompts, draft_custom_template, parse_draft


def reply(sections, name="Ata de kickoff"):
    return json.dumps({"name": name, "sections": sections}, ensure_ascii=False)


def test_the_description_and_the_options_go_into_the_prompt():
    system, user = build_draft_prompts("Quero as decisões e as tarefas.", name="Semanal", tone="informal")
    assert "Formato de saída" in system and "table" in system
    assert "Quero as decisões e as tarefas." in user and "Semanal" in user and "informal" in user


def test_parse_builds_keys_columns_and_validates():
    raw = reply(
        [
            {"title": "Objetivo do projeto", "type": "paragraph", "instructions": "Em até 3 frases.", "columns": []},
            {"title": "Decisões", "type": "bullets", "instructions": "Só o que foi aceito."},
            {
                "title": "Plano de ação",
                "type": "table",
                "instructions": "Tarefas com dono.",
                "columns": ["Tarefa", "Responsável", {"label": "Prazo"}],
            },
        ]
    )
    draft = parse_draft(raw)
    assert draft["name"] == "Ata de kickoff"
    assert [s["key"] for s in draft["sections"]] == ["objetivo_do_projeto", "decisoes", "plano_de_acao"]
    assert draft["sections"][2]["columns"] == [
        {"key": "tarefa", "label": "Tarefa"},
        {"key": "responsavel", "label": "Responsável"},
        {"key": "prazo", "label": "Prazo"},
    ]
    assert "columns" not in draft["sections"][0]
    CustomSpec.model_validate(draft)  # accepted as `custom` by the minutes endpoints


def test_parse_fixes_what_the_model_gets_wrong():
    raw = (
        "```json\n"
        + reply(
            [
                {"title": "Riscos", "type": "mindmap", "instructions": ""},  # unknown type, no instructions
                {"title": "Riscos", "type": "bullets", "instructions": "Outros riscos."},  # same title
                {"title": "Prazos", "type": "table", "columns": ["Prazo"]},  # one-column table
                {"title": "", "type": "bullets"},  # no title: dropped
                "lixo",
            ],
            name="",
        )
        + "\n```"
    )
    draft = parse_draft(raw, tone="formal")
    assert draft["name"] == "Ata personalizada" and draft["tone"] == "formal"
    assert [(s["key"], s["type"]) for s in draft["sections"]] == [
        ("riscos", "bullets"),
        ("riscos_2", "bullets"),
        ("prazos", "bullets"),
    ]
    assert draft["sections"][0]["instructions"]  # a default sentence when the model gave none


def test_parse_refuses_a_reply_without_sections():
    with pytest.raises(ValueError):
        parse_draft(reply([]))
    with pytest.raises(ValueError):
        parse_draft("não sei")


def test_draft_retries_once_then_reports_invalid_response(monkeypatch):
    answers = iter(["não sei", reply([{"title": "Resumo", "type": "paragraph", "instructions": "Resumo."}])])
    monkeypatch.setattr(template_draft.llm, "generate", lambda system, user, **kw: next(answers))
    assert draft_custom_template("Quero só um resumo da reunião.")["sections"][0]["key"] == "resumo"

    monkeypatch.setattr(template_draft.llm, "generate", lambda system, user, **kw: "não sei")
    with pytest.raises(MinutesError) as err:
        draft_custom_template("Quero só um resumo da reunião.")
    assert err.value.code == "llm_invalid_response"


def test_draft_reports_an_unreachable_llm(monkeypatch):
    def down(system, user, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(template_draft.llm, "generate", down)
    with pytest.raises(MinutesError) as err:
        draft_custom_template("Quero só um resumo da reunião.")
    assert err.value.code == "llm_unreachable"


def test_the_fake_provider_gives_a_valid_draft(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    CustomSpec.model_validate(draft_custom_template("Quero o objetivo, as decisões e as tarefas."))
