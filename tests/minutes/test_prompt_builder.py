import json

import pytest

from gravai.minutes.prompt_builder import (
    ResponseValidationError,
    build_merge_prompt,
    build_system_prompt,
    build_user_prompt,
    format_timestamp,
    output_schema,
    parse_response,
    split_transcript,
)
from gravai.minutes.templates import load_template
from gravai.models import Utterance


@pytest.fixture
def dell(meeting):
    """Template, header and Utterance objects of the dataset meeting."""
    return load_template(meeting["template"]), meeting["header"], [Utterance(**u) for u in meeting["utterances"]]


def test_timestamp_format():
    assert format_timestamp(5) == "00:05"
    assert format_timestamp(754.9) == "12:34"
    assert format_timestamp(3725) == "1:02:05"


def test_schema_mirrors_template_sections():
    template = load_template("dell")
    schema = output_schema(template)
    assert list(schema) == [s.key for s in template.sections]
    assert schema["topicos"] == [{"titulo": "texto", "resumo": "texto"}]
    assert schema["plano_acao"][0]["status"] == "Pendente | Em andamento | Concluído"
    assert schema["proxima_reuniao"]["data"] == "DD/MM/AAAA"


def test_system_prompt_carries_tone_and_every_section_instruction():
    template = load_template("professores")
    prompt = build_system_prompt(template)
    assert template.tone in prompt
    for s in template.sections:
        assert f'"{s.key}"' in prompt
        assert s.instructions in prompt
    assert "Não pode ficar vazia" in prompt  # feedback_professores has allow_empty: false


def test_user_prompt_has_header_participants_and_timestamps(dell, speakers):
    template, header, utterances = dell
    prompt = build_user_prompt(template, utterances, header, speakers)
    assert f"- Projeto: {header['projeto']}" in prompt
    assert f"- Participantes: {', '.join(speakers)}" in prompt
    second = utterances[1]
    assert f"[{format_timestamp(second.start)}] {second.speaker}:" in prompt
    assert "Esta é a parte" not in prompt

    chunk = build_user_prompt(template, utterances[:5], header, speakers, part=(1, 3))
    assert "parte 1 de 3" in chunk


def test_split_keeps_one_part_for_short_meetings_and_balances_long_ones(dell):
    _, _, utterances = dell
    assert split_transcript(utterances) == [utterances]

    parts = split_transcript(utterances, max_chars=2000)
    assert len(parts) > 1
    assert [u for p in parts for u in p] == utterances
    sizes = [len(p) for p in parts]
    assert len(set(sizes[:-1])) == 1 and sizes[-1] <= sizes[0]  # consecutive chunks of equal size, remainder last


def test_merge_prompt_lists_every_part(dell, speakers):
    template, header, _ = dell
    prompt = build_merge_prompt(template, [{"resumo": "a"}, {"resumo": "b"}], header, speakers)
    assert "2 JSONs" in prompt and "Parte 1" in prompt and "Parte 2" in prompt


def test_parse_response_fills_missing_sections_numbers_rows_and_strips_fences():
    template = load_template("dell")
    raw = """```json
    {"topicos": [{"titulo": "Integração", "resumo": "Fechada."}],
     "resumo": "Reunião de status.",
     "decisoes": [{"decisao": "Sem réplica de leitura por ora", "aprovada_por": "Carla"}],
     "plano_acao": [{"acao": "Repetir teste de carga", "responsavel": "Diego", "prazo": "03/10"}, {"acao": "", "responsavel": ""}],
     "proxima_reuniao": {"data": "06/10/2026", "horario": "14:00"},
     "campo_extra": "ignorado"}
    ```"""
    minutes = parse_response(template, raw)
    assert list(minutes) == [s.key for s in template.sections]
    assert minutes["finalizado"] == [] and minutes["pendencias"] == []
    assert minutes["decisoes"][0]["id"] == "D1"
    assert minutes["plano_acao"] == [
        {"acao": "Repetir teste de carga", "responsavel": "Diego", "prazo": "03/10", "status": "Pendente", "id": "A1"}
    ]
    assert minutes["proxima_reuniao"] == {"data": "06/10/2026", "horario": "14:00", "pauta": ""}
    assert "campo_extra" not in minutes


def test_parse_response_rejects_bad_json_and_empty_required_sections():
    template = load_template("professores")
    with pytest.raises(ResponseValidationError, match="not valid JSON"):
        parse_response(template, "claro, aqui está a ata: ...")

    with pytest.raises(ResponseValidationError, match="feedback_professores"):
        parse_response(template, json.dumps({"topicos": [{"titulo": "x", "resumo": "y"}], "resumo": "z"}))
