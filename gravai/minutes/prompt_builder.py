import json
import math

from gravai.legacy.llm_analyser.utils import chunk_transcript, extract_json_from_response
from gravai.minutes.templates import MinutesTemplate, Section, load_template
from gravai.models import Utterance

# Rough size of transcript text sent in one request. Portuguese runs at about 3.5
# characters per token, so 24k characters is close to 7k tokens of transcript,
# which leaves room for the instructions on a 8k-token free-tier budget.
DEFAULT_MAX_CHARS = 24_000


class ResponseValidationError(ValueError):
    pass


# ---------------------------------------------------------------- transcript


def format_timestamp(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_transcript(utterances: list[Utterance]) -> str:
    return "\n".join(f"[{format_timestamp(u.start)}] {u.speaker}: {u.text}" for u in utterances)


def split_transcript(utterances: list[Utterance], max_chars: int = DEFAULT_MAX_CHARS) -> list[list[Utterance]]:
    """Splits the transcript into consecutive parts of roughly max_chars each. One part when it fits."""
    total = len(format_transcript(utterances))
    if not utterances or total <= max_chars:
        return [utterances]
    parts = math.ceil(total / max_chars)
    return chunk_transcript(utterances, math.ceil(len(utterances) / parts))


# ------------------------------------------------------------- output schema


def _column_hint(col) -> str:
    if col.values:
        return " | ".join(col.values)
    return col.format or "texto"


def output_schema(template: MinutesTemplate) -> dict:
    """The JSON shape the model must return, with a type hint in place of every value."""
    schema = {}
    for s in template.sections:
        if s.type == "paragraph":
            schema[s.key] = "texto"
        elif s.type == "bullets":
            schema[s.key] = ["texto"]
        elif s.type == "topics":
            schema[s.key] = [{"titulo": "texto", "resumo": "texto"}]
        elif s.type == "table":
            schema[s.key] = [{c.key: _column_hint(c) for c in s.columns}]
        elif s.type == "record":
            schema[s.key] = {f.key: _column_hint(f) for f in s.fields}
    return schema


def _describe_section(s: Section) -> str:
    kind = {
        "paragraph": "texto corrido",
        "bullets": "lista de itens curtos",
        "topics": "lista de tópicos com titulo e resumo",
        "table": "tabela, uma linha por item",
        "record": "um único registro",
    }[s.type]
    lines = [f'- "{s.key}" ({s.title}, {kind}): {s.instructions}']
    if s.min_items:
        lines.append(f"  Mínimo de {s.min_items} {'item' if s.min_items == 1 else 'itens'}.")
    elif s.allow_empty:
        lines.append("  Pode ficar vazia quando a reunião não tiver esse conteúdo.")
    elif s.required and s.type in ("bullets", "topics", "table"):
        lines.append("  Não pode ficar vazia.")
    for f in s.columns or s.fields or []:
        detail = []
        if f.instructions:
            detail.append(f.instructions.rstrip("."))
        if f.values:
            detail.append("valores permitidos: " + ", ".join(f.values))
        if f.default:
            detail.append(f"padrão: {f.default}")
        if f.format:
            detail.append(f"formato: {f.format}")
        if detail:
            lines.append(f'  · "{f.key}" ({f.label}): ' + "; ".join(detail) + ".")
    return "\n".join(lines)


# ----------------------------------------------------------------- prompts


def build_system_prompt(template: MinutesTemplate) -> str:
    sections = "\n".join(_describe_section(s) for s in template.sections)
    schema = json.dumps(output_schema(template), ensure_ascii=False, indent=2)
    return f"""Você redige atas de reunião a partir de transcrições automáticas de áudio. A saída é lida por pessoas que não participaram da reunião e precisa ser suficiente por si só.

Modelo de ata: {template.name}.
Idioma: {template.language}.
Tom: {template.tone}

Regras
1. Use somente o que está na transcrição. Não invente fatos, nomes, números, datas, prazos ou decisões. O que não foi dito fica vazio ("" ou []).
2. A transcrição vem de reconhecimento de fala: pode ter erros de palavras, repetições, frases cortadas e trechos sem sentido. Corrija erros óbvios pelo contexto, ignore ruído e não reproduza a fala literalmente; reescreva em texto de ata.
3. Pessoas: use os nomes exatamente como aparecem na lista de participantes. Não use "eu", "você" nem "o falante".
4. Datas e prazos: só quando forem ditos. Expressões relativas ("sexta que vem", "daqui a duas semanas") devem ser convertidas para data quando a data da reunião permitir calcular; caso contrário, escreva a expressão como foi dita.
5. Cada informação entra em uma única seção. Decisão é uma escolha fechada nesta reunião, por acordo explícito ou por concordância sem objeção; uma proposta aceita é decisão, não ideia; o que foi decidido em reunião anterior e só foi relembrado não é decisão desta ata (pode aparecer no resumo). Ação é uma tarefa com dono; pendência é algo que depende de alguém e não virou ação; dúvida é uma pergunta que ficou sem resposta.
6. Não numere itens de tabela (D1, A1): a numeração é feita depois. Os tempos entre colchetes na transcrição servem só de orientação e não entram na ata.
7. Seja conciso. Prefira frases curtas e concretas a generalidades.
8. Responda somente com um objeto JSON válido, sem texto antes ou depois, sem markdown e sem comentários, exatamente com as chaves do formato abaixo.

Formato de saída
{schema}

Conteúdo de cada chave
{sections}"""


def _header_block(template: MinutesTemplate, header: dict, participants: list[str]) -> str:
    lines = ["Dados da reunião"]
    for field in template.header:
        value = header.get(field.key)
        if value:
            lines.append(f"- {field.label}: {value}")
    lines.append("- Participantes: " + ", ".join(participants))
    return "\n".join(lines)


def build_user_prompt(
    template: MinutesTemplate,
    utterances: list[Utterance],
    header: dict,
    participants: list[str],
    part: tuple[int, int] | None = None,
) -> str:
    """
    The per-request prompt. `part=(i, n)` marks this as part i of n of a long
    transcript, in which case the model fills the JSON with that part only.
    """
    duration = format_timestamp(utterances[-1].end) if utterances else "00:00"
    blocks = [_header_block(template, header, participants)]
    if part:
        i, n = part
        blocks.append(
            f"Esta é a parte {i} de {n} da transcrição. Preencha o JSON apenas com o que aparece nesta parte; "
            "as seções sem conteúdo nesta parte ficam vazias. O resumo deve cobrir apenas esta parte."
        )
    blocks.append(f"Transcrição ({len(utterances)} falas, duração {duration})\n{format_transcript(utterances)}")
    blocks.append("Gere o JSON da ata.")
    return "\n\n".join(blocks)


def build_merge_prompt(template: MinutesTemplate, partials: list[dict], header: dict, participants: list[str]) -> str:
    """Second pass for long meetings: consolidates the JSONs of each part into one."""
    parts = "\n\n".join(f"Parte {i}\n{json.dumps(p, ensure_ascii=False, indent=2)}" for i, p in enumerate(partials, 1))
    return f"""{_header_block(template, header, participants)}

Abaixo estão {len(partials)} JSONs gerados a partir de partes consecutivas da mesma reunião. Consolide tudo em um único JSON final com as mesmas chaves:
- mantenha a ordem cronológica dos itens;
- junte itens repetidos entre as partes em um só;
- quando uma parte posterior atualiza algo de uma parte anterior (status, prazo, responsável), vale a versão mais recente;
- uma ideia de uma parte que foi aceita em outra vira decisão; uma decisão desfeita ou mudada depois fica só na versão final;
- reescreva o texto corrido para cobrir a reunião inteira, sem mencionar "partes".

{parts}

Gere o JSON final da ata."""


# ---------------------------------------------------------------- response


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_as_text(v) for v in value).strip()
    if isinstance(value, dict):
        return " ".join(_as_text(v) for v in value.values()).strip()
    return str(value).strip()


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _row(fields, raw: dict | str) -> dict:
    if not isinstance(raw, dict):
        raw = {fields[0].key: raw}
    row = {}
    for f in fields:
        text = _as_text(raw.get(f.key))
        if not text and f.default:
            text = f.default
        row[f.key] = text
    return row


def _coerce_section(s: Section, value):
    if s.type == "paragraph":
        return _as_text(value)
    if s.type == "bullets":
        return [t for t in (_as_text(v) for v in _as_list(value)) if t]
    if s.type == "topics":
        topics = []
        for v in _as_list(value):
            if isinstance(v, dict):
                topic = {"titulo": _as_text(v.get("titulo")), "resumo": _as_text(v.get("resumo"))}
            else:
                topic = {"titulo": _as_text(v), "resumo": ""}
            if topic["titulo"] or topic["resumo"]:
                topics.append(topic)
        return topics
    if s.type == "table":
        rows = [_row(s.columns, v) for v in _as_list(value)]
        rows = [r for r in rows if any(r[c.key] for c in s.columns if not c.default)]
        for i, r in enumerate(rows, 1):
            r["id"] = f"{s.id_prefix or ''}{i}"
        return rows
    if s.type == "record":
        return _row(s.fields, value if isinstance(value, dict) else {})


def parse_response(template: MinutesTemplate, raw: str) -> dict:
    """
    Turns the model's reply into a dict with exactly the template's section keys,
    every value in the shape the docx writer expects. Missing sections become
    empty; sections that must not be empty raise ResponseValidationError.
    """
    try:
        data = json.loads(extract_json_from_response(raw))
    except json.JSONDecodeError as exc:
        raise ResponseValidationError(f"model reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ResponseValidationError("model reply is not a JSON object")

    minutes = {}
    problems = []
    for s in template.sections:
        value = _coerce_section(s, data.get(s.key))
        minutes[s.key] = value
        empty = not value or (s.type == "record" and not any(value.values()))
        if empty and s.required and not s.allow_empty:
            problems.append(f"'{s.key}' is required and came back empty")
        if s.min_items and len(value) < s.min_items:
            problems.append(f"'{s.key}' needs at least {s.min_items} item(s), got {len(value)}")
    if problems:
        raise ResponseValidationError("; ".join(problems))
    return minutes


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Print the prompts built for a transcript file (to run them through the LLM use `python -m minutes.generate`)"
    )
    parser.add_argument(
        "transcript", help="JSON with template, header and utterances, e.g. datasets/reunioes/ES2004a/transcricao.json"
    )
    parser.add_argument(
        "--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="transcript characters per request before splitting"
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(args.transcript, encoding="utf-8") as f:
        transcript = json.load(f)
    template = load_template(transcript["template"])
    utterances = [Utterance(**u) for u in transcript["utterances"]]
    participants = sorted({u.speaker for u in utterances})
    parts = split_transcript(utterances, args.max_chars)

    print("=== SYSTEM ===\n" + build_system_prompt(template))
    for i, p in enumerate(parts, 1):
        user = build_user_prompt(
            template, p, transcript["header"], participants, part=(i, len(parts)) if len(parts) > 1 else None
        )
        print(f"\n=== USER {i}/{len(parts)} ===\n" + user)
