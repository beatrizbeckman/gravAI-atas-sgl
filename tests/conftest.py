"""
Shared test data. Transcripts come from the real dataset in datasets/reunioes/
(AMI meeting ES2004a translated to pt-BR); nothing is invented here except the
filled minutes below, which stand for a good model reply so the parser, the
docx writer and the pipeline can be tested without an LLM.
"""

import copy

import pytest

from gravai.minutes.dataset import load_meeting

MEETING_ID = "ES2004a"  # the shortest meeting of the dataset: 4 speakers, ~19 min

# A plausible, complete answer for the "dell" template on ES2004a. Table rows
# carry their ids the way the pipeline numbers them (D1.., A1..).
FILLED_MINUTES = {
    "topicos": [
        {
            "titulo": "Abertura e apresentação da equipe",
            "resumo": "Paula apresentou o projeto do controle remoto e conduziu uma dinâmica de desenho para a equipe se conhecer.",
        },
        {
            "titulo": "Preço e público-alvo",
            "resumo": "Preço de venda de 25 euros com custo de produção de 12,50; mercado internacional e todas as faixas etárias.",
        },
        {
            "titulo": "Estilo e design do controle",
            "resumo": "Um controle para todos os aparelhos, fácil de usar, com botões básicos e menu na tela.",
        },
    ],
    "resumo": "Reunião de kickoff do projeto Controle Remoto Universal: metas financeiras, público-alvo e primeiras decisões de design.",
    "finalizado": ["Apresentação do projeto e da equipe"],
    "em_andamento": ["Definição do estilo do controle"],
    "ideias_propostas": ["Integrar controles de vários aparelhos em um só", "Menu na tela em vez de muitos botões"],
    "duvidas": ["A tampa flip compensa o custo adicional?"],
    "pendencias": [],
    "decisoes": [
        {
            "id": "D1",
            "decisao": "Preço de venda de 25 euros, custo de produção de 12,50 euros",
            "aprovada_por": "Paula",
        },
        {"id": "D2", "decisao": "Botões básicos com menu intuitivo na tela", "aprovada_por": "Equipe"},
        {"id": "D3", "decisao": "Plástico leve prateado como material provisório", "aprovada_por": "Equipe"},
    ],
    "plano_acao": [
        {
            "id": "A1",
            "acao": "Pesquisar as necessidades dos usuários",
            "responsavel": "Marina",
            "prazo": "09/03/2026",
            "status": "Pendente",
        },
        {
            "id": "A2",
            "acao": "Detalhar os requisitos técnicos",
            "responsavel": "Diego",
            "prazo": "09/03/2026",
            "status": "Pendente",
        },
        {
            "id": "A3",
            "acao": "Esboçar a interface do controle",
            "responsavel": "Ulisses",
            "prazo": "A definir",
            "status": "Pendente",
        },
    ],
    "proxima_reuniao": {
        "data": "09/03/2026",
        "horario": "14:00",
        "pauta": "Projeto funcional: requisitos e necessidades dos usuários",
    },
}


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """An API_KEY in the local .env must not leak into the tests; the ones about the key set it."""
    monkeypatch.setenv("API_KEY", "")


@pytest.fixture(scope="session")
def _meeting_file() -> dict:
    return load_meeting(MEETING_ID)


@pytest.fixture
def meeting(_meeting_file) -> dict:
    """ES2004a as the API receives it: template, header and every utterance."""
    data = copy.deepcopy(_meeting_file)
    return {"template": data["template"], "header": data["header"], "utterances": data["utterances"]}


@pytest.fixture
def short_meeting(meeting) -> dict:
    """The first 40 utterances of ES2004a (all four speakers appear), for tests that do not need the whole meeting."""
    return {**meeting, "utterances": meeting["utterances"][:40]}


@pytest.fixture
def speakers(meeting) -> list[str]:
    return sorted({u["speaker"] for u in meeting["utterances"]})


@pytest.fixture
def filled_minutes() -> dict:
    return copy.deepcopy(FILLED_MINUTES)
