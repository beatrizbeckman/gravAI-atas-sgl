"""
Turns a plain-language description of the minutes someone wants ("quero o
objetivo, as decisões e as tarefas com responsável") into a custom template
with sections. The client (the SGL) shows the draft, the user adjusts it and
saves it as the project's model, then sends it as `custom` in the minutes
requests.

Free instructions alone (CustomSpec.instructions) also work, but give one
block of text; declared sections give a structured minutes with lists and
tables, like the fixed templates. This module gets the second from the first.

The model only proposes titles, types, instructions and column names. Keys,
type fallbacks and limits are fixed here, and the result is validated as a
CustomSpec, so a draft is always accepted by the minutes endpoints.
"""

import json
import unicodedata

import requests

from gravai.legacy.llm_analyser.utils import extract_json_from_response
from gravai.minutes import llm
from gravai.minutes.custom_template import MAX_SECTIONS, CustomSpec
from gravai.minutes.generate import MinutesError

DRAFT_TYPES = ("paragraph", "bullets", "topics", "table")
MAX_COLUMNS = 6
ATTEMPTS = 2
# Someone is waiting on the screen for the draft: only short pauses when the provider rate-limits.
DRAFT_RATE_LIMIT_WAITS = (5, 15)

# Shown to the model as the output format; the fake provider also fills it in (see llm.fake_generate).
_OUTPUT_EXAMPLE = {
    "name": "texto",
    "sections": [
        {
            "title": "texto",
            "type": "paragraph | bullets | topics | table",
            "instructions": "texto",
            "columns": ["texto"],
        }
    ],
}


def build_draft_prompts(description: str, name: str | None = None, tone: str | None = None) -> tuple[str, str]:
    system = f"""Você ajuda a montar o modelo de uma ata de reunião. A pessoa descreve em linguagem comum como quer a ata; você devolve as seções que a ata deve ter. Depois, outra IA vai preencher essas seções a partir da transcrição de cada reunião.

Regras
1. Uma seção para cada coisa que a pessoa pediu, na ordem em que pediu. Não acrescente seções que ela não pediu. Se a descrição for vaga, proponha no máximo 5 seções comuns (por exemplo resumo, decisões e tarefas).
2. Tipo de cada seção:
   - paragraph: texto corrido (resumo, objetivo, contexto);
   - bullets: lista de itens curtos (decisões, dúvidas, riscos, pendências);
   - topics: assuntos discutidos, cada um com um título e um resumo;
   - table: linhas com várias informações por item (por exemplo tarefa, responsável e prazo). Dê os nomes das colunas em "columns".
3. "title": título curto da seção, em português, como vai aparecer na ata.
4. "instructions": uma ou duas frases dizendo o que deve entrar na seção e, quando importar, o que não entra.
5. "columns": só em seções do tipo table, de 2 a {MAX_COLUMNS} nomes de coluna; nas outras, lista vazia.
6. No máximo {MAX_SECTIONS} seções.
7. "name": um nome curto para o modelo de ata.
8. Responda somente com um objeto JSON válido, sem texto antes ou depois, sem markdown e sem comentários.

Formato de saída
{json.dumps(_OUTPUT_EXAMPLE, ensure_ascii=False, indent=2)}

Conteúdo de cada chave
- name: nome do modelo de ata.
- sections: as seções, na ordem em que vão aparecer na ata."""
    user = f"Descrição da ata que a pessoa quer:\n{description.strip()}"
    if name:
        user += f"\n\nNome que a pessoa deu ao modelo: {name.strip()}"
    if tone:
        user += f"\n\nTom pedido para a ata: {tone.strip()}"
    return system, user


def _key(text: str) -> str:
    """'Plano de ação' -> 'plano_de_acao', the snake_case key the templates use."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    key = "".join(ch if ch.isalnum() else "_" for ch in ascii_text)
    key = "_".join(part for part in key.split("_") if part)[:40].rstrip("_")
    if not key or not key[0].isalpha():
        key = f"secao_{key}".rstrip("_")
    return key


def _unique(key: str, used: set[str]) -> str:
    candidate, n = key, 2
    while candidate in used:
        candidate, n = f"{key}_{n}", n + 1
    used.add(candidate)
    return candidate


def _column_label(column) -> str:
    if isinstance(column, dict):
        column = column.get("label") or column.get("title") or column.get("key") or ""
    return str(column).strip()


def parse_draft(raw: str, name: str | None = None, tone: str | None = None) -> dict:
    """The model reply as a valid `custom` object. Raises ValueError when nothing usable came back."""
    data = json.loads(extract_json_from_response(raw))
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    sections, used = [], set()
    for proposed in (data.get("sections") or [])[:MAX_SECTIONS]:
        if not isinstance(proposed, dict):
            continue
        title = str(proposed.get("title") or "").strip()
        if not title:
            continue
        kind = proposed.get("type") if proposed.get("type") in DRAFT_TYPES else "bullets"
        section = {
            "key": _unique(_key(title), used),
            "title": title,
            "type": kind,
            "instructions": str(proposed.get("instructions") or "").strip()
            or f"O que foi dito na reunião sobre {title.lower()}.",
        }
        if kind == "table":
            labels = [label for label in map(_column_label, proposed.get("columns") or []) if label][:MAX_COLUMNS]
            if len(labels) < 2:
                section["type"] = "bullets"  # a one-column table is a list
            else:
                column_keys: set[str] = set()
                section["columns"] = [{"key": _unique(_key(label), column_keys), "label": label} for label in labels]
        sections.append(section)
    if not sections:
        raise ValueError("the model proposed no sections")
    draft = {"name": (name or str(data.get("name") or "")).strip() or "Ata personalizada", "sections": sections}
    if tone and tone.strip():
        draft["tone"] = tone.strip()
    CustomSpec.model_validate(draft)  # the same rules as a `custom` sent by a client
    return draft


def draft_custom_template(description: str, name: str | None = None, tone: str | None = None) -> dict:
    """Asks the configured LLM for the sections. Raises MinutesError with the contract's codes."""
    system, user = build_draft_prompts(description, name, tone)
    last_problem: Exception | None = None
    for _ in range(ATTEMPTS):
        try:
            raw = llm.generate(system, user, rate_limit_waits=DRAFT_RATE_LIMIT_WAITS)
        except (requests.RequestException, RuntimeError) as exc:
            raise MinutesError("llm_unreachable", str(exc)) from exc
        try:
            return parse_draft(raw, name, tone)
        except ValueError as exc:  # also JSONDecodeError and pydantic's ValidationError
            last_problem = exc
    raise MinutesError("llm_invalid_response", f"could not turn the description into sections: {last_problem}")
