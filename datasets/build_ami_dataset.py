"""
Builds the meeting-transcript dataset from AMI meetings, in the same format the
minutes pipeline consumes (template + header + utterances), translated to pt-BR.

Sources
- Text and human summaries: QMSum (Yale-LILY/QMSum), which carries the AMI
  transcripts with punctuation, casing and the speaker's project role, plus a
  human-written summary, a topic list and question/answer pairs per meeting.
- Timing: edinburghcstr/ami on Hugging Face (begin/end of each segment). When
  that API is unavailable the timestamps are interpolated from word counts.

For each meeting the output folder datasets/reunioes/<id>/ holds
- original.json      English utterances after cleanup (speaker, start, end, text)
- transcricao.json   the fixture the pipeline reads: template, header, utterances in pt-BR
- gabarito.md        what the minutes must contain: summary, topics and Q&A, translated
- traducao_cache.json  translated chunks, so an interrupted run resumes

Usage
    uv run python datasets/build_ami_dataset.py                 # all five meetings
    uv run python datasets/build_ami_dataset.py ES2004a         # one meeting
    uv run python datasets/build_ami_dataset.py --no-translate  # only convert

The translation uses the online provider configured in .env (LLM_BASE_URL,
LLM_API_KEY) with the model given by --model (default: a large one, because
translation quality is the ceiling of the whole dataset).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import ClassVar

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gravai.config import Settings
from gravai.minutes import llm
from gravai.minutes.dataset import read_json, write_json, write_text

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "raw", "qmsum")
OUT_DIR = os.path.join(HERE, "reunioes")

QMSUM_RAW = "https://raw.githubusercontent.com/Yale-LILY/QMSum/main/data/ALL/{split}/{meeting}.json"
HF_FILTER = "https://datasets-server.huggingface.co/filter"

# Meeting -> (QMSum split, HF split). The AMI scenario: a team of four designs a new TV remote control.
MEETINGS = {
    "ES2004a": ("test", "test"),
    "ES2004b": ("test", "test"),
    "ES2004c": ("test", "test"),
    "ES2004d": ("test", "test"),
    "TS3003d": ("train", "test"),
}

# Each AMI series is a different team, so each gets its own fictitious names.
NAMES = {
    "ES2004": {
        "Project Manager": "Paula",
        "Industrial Designer": "Diego",
        "User Interface": "Ulisses",
        "Marketing": "Marina",
    },
    "TS3003": {
        "Project Manager": "Pedro",
        "Industrial Designer": "Davi",
        "User Interface": "Úrsula",
        "Marketing": "Mariana",
    },
}
ROLES_PT = {
    "Project Manager": "Gerente de Projeto",
    "Industrial Designer": "Designer Industrial",
    "User Interface": "Designer de Interface",
    "Marketing": "Marketing",
}
# Kickoff, functional design, conceptual design, detailed design: the four AMI scenario phases.
PHASE = {"a": "Kickoff do projeto", "b": "Projeto funcional", "c": "Projeto conceitual", "d": "Projeto detalhado"}

WORDS_PER_SECOND = 2.6  # conversational English, used only when real timing is unavailable
TURN_GAP_SECONDS = 0.4
CHUNK_TURNS = 30
# gpt-oss models spend part of the reply on hidden reasoning; without a cap the
# translation of a 40-turn chunk was cut at ~3k tokens. Low effort is enough to translate.
MAX_TOKENS = 8000
EXTRA = {"reasoning_effort": "low"}


# ----------------------------------------------------------------- download


def fetch_qmsum(meeting: str) -> dict:
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, f"{meeting}.json")
    if not os.path.exists(path):
        split = MEETINGS[meeting][0]
        r = requests.get(QMSUM_RAW.format(split=split, meeting=meeting), timeout=60)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
    return json.load(open(path, encoding="utf-8"))


def fetch_ami_duration(meeting: str) -> float | None:
    """Last end_time of the meeting in edinburghcstr/ami, or None when the API is not ready."""
    params = {
        "dataset": "edinburghcstr/ami",
        "config": "ihm",
        "split": MEETINGS[meeting][1],
        "where": f"\"meeting_id\"='{meeting}'",
        "orderby": '"end_time" DESC',
        "offset": 0,
        "length": 1,
    }
    try:
        r = requests.get(HF_FILTER, params=params, timeout=60)
        rows = r.json().get("rows") or []
        return float(rows[0]["row"]["end_time"]) if rows else None
    except (requests.RequestException, ValueError, KeyError):
        return None


# ------------------------------------------------------------------ cleanup

_MARKERS = re.compile(r"\{(vocalsound|disfmarker|gap|pause|nonvocalsound)\}", re.I)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?;:])")
_SPACE_IN_CONTRACTION = re.compile(r"\s+('(?:s|re|ve|ll|d|m|t)\b|n't\b)")


def clean_text(text: str) -> str:
    text = _MARKERS.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _SPACE_IN_CONTRACTION.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    # A turn that was only a vocal sound ends up as "." or empty.
    return "" if re.fullmatch(r"[.,!?;:\s]*", text) else text


def to_utterances(qmsum: dict, meeting: str, duration: float | None) -> list[dict]:
    names = NAMES[meeting[:6]]
    turns = [(names[t["speaker"]], clean_text(t["content"])) for t in qmsum["meeting_transcripts"]]
    turns = [(s, c) for s, c in turns if c]

    # Spread the turns over the meeting: duration proportional to words, a small gap between turns.
    words = [max(1, len(c.split())) for _, c in turns]
    estimated = sum(w / WORDS_PER_SECOND + TURN_GAP_SECONDS for w in words)
    scale = (duration / estimated) if duration else 1.0

    utterances, clock = [], 0.0
    for (speaker, content), w in zip(turns, words, strict=False):
        length = (w / WORDS_PER_SECOND) * scale
        utterances.append(
            {"speaker": speaker, "start": round(clock, 2), "end": round(clock + length, 2), "text": content}
        )
        clock += length + TURN_GAP_SECONDS * scale
    return utterances


# -------------------------------------------------------------- translation

TRANSLATE_SYSTEM = (
    "Você traduz transcrições de reuniões do inglês para o português do Brasil. "
    "A transcrição é de fala espontânea, gravada e transcrita automaticamente. Regras:\n"
    "1. Mantenha o registro oral: hesitações, frases incompletas, repetições, 'né', 'tipo', 'hum'. Não melhore nem resuma.\n"
    "2. Traduza cada fala separadamente e preserve o sentido exato, inclusive números, valores e termos técnicos.\n"
    "3. Nomes próprios dos participantes ficam como estão. 'Euro(s)' vira 'euro(s)'.\n"
    '4. Responda apenas com um objeto JSON no formato {"falas": [{"id": <mesmo id>, "texto": "<tradução>"}, ...]}, '
    "com exatamente os mesmos ids da entrada, na mesma ordem."
)

SUMMARY_SYSTEM = (
    "Você traduz textos sobre reuniões do inglês para o português do Brasil, com fidelidade e em registro formal. "
    "Substitua os papéis pelos nomes indicados no campo 'nomes' de cada item. "
    'Responda apenas com um objeto JSON no formato {"itens": [{"id": <mesmo id>, "texto": "<tradução>"}, ...]}.'
)


class Translator:
    def __init__(self, model: str, cache_path: str):
        settings = Settings()
        self.cfg = {
            "base_url": settings.LLM_BASE_URL,
            "api_key": settings.LLM_API_KEY,
            "model": model,
            "timeout": 180,
            "max_tokens": MAX_TOKENS,
            "extra": EXTRA,
        }
        self.cache_path = cache_path
        self.cache = read_json(cache_path) if os.path.exists(cache_path) else {}
        self.tokens = 0

    def _save(self):
        write_json(self.cache_path, self.cache)

    def _call(self, system: str, user: str) -> str:
        reply = llm.openai_chat_retrying(system, user, log=lambda msg: print(f"    {msg}", flush=True), **self.cfg)
        self.tokens += reply.usage.get("total_tokens", 0)
        return reply.content

    def _ask(self, system: str, key_field: str, items: list[dict]) -> dict[int, str]:
        """
        items: [{"id", ...}] to translate. Replies that come back truncated or
        with ids missing trigger a new request with only the missing items.
        """
        out: dict[int, str] = {}
        pending = list(items)
        for _attempt in range(6):
            raw = self._call(system, json.dumps({key_field: pending}, ensure_ascii=False))
            try:
                for i in json.loads(raw)[key_field]:
                    text = str(i["texto"]).strip()
                    if text:
                        out[int(i["id"])] = text
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                print(f"    bad JSON from model ({exc}), retrying", flush=True)
            pending = [i for i in pending if i["id"] not in out]
            if not pending:
                return out
            print(f"    {len(pending)} ids missing in reply, asking again for those", flush=True)
        raise RuntimeError(f"translation failed: {len(pending)} ids still missing after 6 attempts")

    def models_used(self) -> list[str]:
        """Models that produced the cached chunks (several when a run was finished with another model)."""
        return sorted(set(self.cache.get("_models", {}).values()) or {self.cfg["model"]})

    def _cached_turns(self) -> dict[int, str]:
        """Every translated turn in the cache, whatever chunk size wrote it."""
        cached: dict[int, str] = {}
        for key, chunk in self.cache.items():
            if key.startswith("turns:") and isinstance(chunk, dict):
                cached.update({int(i): t for i, t in chunk.items()})
        return cached

    def _store_turn(self, i: int, text: str):
        for key, chunk in self.cache.items():
            if key.startswith("turns:") and isinstance(chunk, dict) and str(i) in chunk:
                chunk[str(i)] = text
                return
        self.cache.setdefault(f"turns:{(i // CHUNK_TURNS) * CHUNK_TURNS}", {})[str(i)] = text

    def translate_turns(self, utterances: list[dict]) -> list[str]:
        cached = self._cached_turns()
        missing = [i for i in range(len(utterances)) if i not in cached]
        for start in range(0, len(missing), CHUNK_TURNS):
            ids = missing[start : start + CHUNK_TURNS]
            items = [{"id": i, "quem": utterances[i]["speaker"], "texto": utterances[i]["text"]} for i in ids]
            print(f"    translating turns {ids[0]}-{ids[-1]}", flush=True)
            out = self._ask(TRANSLATE_SYSTEM, "falas", items)  # raises when ids are still missing
            key = f"turns:{ids[0]}"
            self.cache[key] = {str(i): out[i] for i in ids}
            self.cache.setdefault("_models", {})[key] = self.cfg["model"]
            self._save()
            cached.update(out)
        result = [cached[i] for i in range(len(utterances))]
        self._repair(utterances, result)
        return result

    # Short turns that are legitimately the same in both languages.
    _SAME_OK: ClassVar[frozenset[str]] = frozenset(
        {"mm-hmm.", "mm.", "hmm.", "ok.", "okay.", "yeah.", "yep.", "no.", "mm hmm.", "uh-huh.", "ah.", "oh."}
    )

    def _repair(self, utterances: list[dict], result: list[str]):
        """
        Earlier runs kept the English text when the model skipped an id. Find
        turns still identical to the source and translate just those, updating
        the cached chunk so the fix is permanent.
        """
        todo = [
            i
            for i, (u, t) in enumerate(zip(utterances, result, strict=False))
            if t.strip().lower() == u["text"].strip().lower() and len(t) > 8 and t.strip().lower() not in self._SAME_OK
        ]
        if not todo:
            return
        print(f"    repairing {len(todo)} turns left in English", flush=True)
        items = [{"id": i, "quem": utterances[i]["speaker"], "texto": utterances[i]["text"]} for i in todo]
        out = self._ask(TRANSLATE_SYSTEM, "falas", items)
        for i, text in out.items():
            result[i] = text
            self._store_turn(i, text)
        self.cache.setdefault("_models", {})["repair"] = self.cfg["model"]
        self._save()

    def translate_items(self, key: str, texts: list[str], names_note: str) -> list[str]:
        if key not in self.cache:
            items = [{"id": i, "nomes": names_note, "texto": t} for i, t in enumerate(texts)]
            print(f"    translating {key} ({len(texts)} items)", flush=True)
            out = self._ask(SUMMARY_SYSTEM, "itens", items)
            self.cache[key] = [out.get(i, texts[i]) for i in range(len(texts))]
            self.cache.setdefault("_models", {})[key] = self.cfg["model"]
            self._save()
        return self.cache[key]


# -------------------------------------------------------------------- build


def header_for(meeting: str, utterances: list[dict]) -> dict:
    letter = meeting[-1]
    number = {"a": "001", "b": "002", "c": "003", "d": "004"}[letter]
    # One fictitious date per phase, a week apart, so "next meeting" references can be resolved.
    day = {"a": "02", "b": "09", "c": "16", "d": "23"}[letter]
    minutes = round(utterances[-1]["end"] / 60) if utterances else 0
    end_h, end_m = divmod(14 * 60 + minutes, 60)
    return {
        "projeto": "Controle Remoto Universal",
        "numero": number,
        "data": f"{day}/03/2026",
        "horario": f"14:00 – {end_h:02d}:{end_m:02d}",
    }


def write_gabarito(path: str, meeting: str, qmsum: dict, translated: dict | None, duration_source: str):
    names = NAMES[meeting[:6]]
    lines = [f"# Gabarito · {meeting} · {PHASE[meeting[-1]]}", ""]
    lines += [
        "Fonte: AMI Meeting Corpus via QMSum (resumo, tópicos e perguntas escritos por humanos), traduzido para pt-BR."
        f" Tempos: {duration_source}.",
        "",
    ]
    lines += ["## Participantes", "", "| Nome na transcrição | Papel no AMI |", "|---|---|"]
    lines += [f"| {n} | {ROLES_PT[r]} ({r}) |" for r, n in names.items()]
    lines += ["", "## Resumo da reunião (humano)", ""]
    general = [q["answer"] for q in qmsum["general_query_list"]]
    topics = [t["topic"] for t in qmsum["topic_list"]]
    specific = [(q["query"], q["answer"]) for q in qmsum["specific_query_list"]]
    if translated:
        general_t, topics_t = translated["general"], translated["topics"]
        specific_t = list(zip(translated["questions"], translated["answers"], strict=False))
    else:
        general_t, topics_t, specific_t = general, topics, specific
    lines += general_t + ["", "## Tópicos discutidos", ""] + [f"- {t}" for t in topics_t]
    lines += ["", "## Perguntas e respostas (o que a ata precisa cobrir)", ""]
    for q, a in specific_t:
        lines += [f"**{q}**", "", a, ""]
    lines += ["## Original (inglês)", "", "<details><summary>abrir</summary>", "", *general, ""]
    lines += [f"- {t}" for t in topics] + [""]
    for q, a in specific:
        lines += [f"**{q}**", "", a, ""]
    lines += ["</details>", ""]
    write_text(path, "\n".join(lines))


def build(meeting: str, translate: bool, model: str):
    print(f"== {meeting}", flush=True)
    out = os.path.join(OUT_DIR, meeting)
    os.makedirs(out, exist_ok=True)

    qmsum = fetch_qmsum(meeting)
    duration = fetch_ami_duration(meeting)
    duration_source = (
        f"reais, duração {duration / 60:.1f} min (edinburghcstr/ami)"
        if duration
        else "estimados pelo número de palavras (API do edinburghcstr/ami indisponível na construção)"
    )
    print(f"   timing: {duration_source}", flush=True)

    utterances = to_utterances(qmsum, meeting, duration)
    write_json(
        os.path.join(out, "original.json"), {"meeting_id": meeting, "source": "QMSum/AMI", "utterances": utterances}
    )
    print(f"   {len(utterances)} utterances, {sum(len(u['text']) for u in utterances)} chars (en)", flush=True)

    translated = None
    if translate:
        tr = Translator(model, os.path.join(out, "traducao_cache.json"))
        texts = tr.translate_turns(utterances)
        utterances = [{**u, "text": t} for u, t in zip(utterances, texts, strict=False)]
        names_note = "; ".join(f"{r} = {n}" for r, n in NAMES[meeting[:6]].items())
        general = tr.translate_items("general", [q["answer"] for q in qmsum["general_query_list"]], names_note)
        topics = tr.translate_items("topics", [t["topic"] for t in qmsum["topic_list"]], names_note)
        questions = tr.translate_items("questions", [q["query"] for q in qmsum["specific_query_list"]], names_note)
        answers = tr.translate_items("answers", [q["answer"] for q in qmsum["specific_query_list"]], names_note)
        translated = {"general": general, "topics": topics, "questions": questions, "answers": answers}
        model = " + ".join(tr.models_used())
        print(f"   translation used {tr.tokens} tokens with {model}", flush=True)

    fixture = {
        "template": "dell",
        "header": header_for(meeting, utterances),
        "utterances": utterances,
        "meta": {
            "source": "AMI Meeting Corpus (QMSum transcript + edinburghcstr/ami timing)",
            "meeting_id": meeting,
            "phase": PHASE[meeting[-1]],
            "language": "pt-BR" if translate else "en",
            "translation_model": model if translate else None,
            "timing": duration_source,
        },
    }
    write_json(os.path.join(out, "transcricao.json"), fixture)
    write_gabarito(os.path.join(out, "gabarito.md"), meeting, qmsum, translated, duration_source)
    print(f"   -> {out}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("meetings", nargs="*", default=list(MEETINGS), help="AMI meeting ids (default: all five)")
    parser.add_argument("--no-translate", action="store_true", help="only convert, keep English")
    parser.add_argument("--model", default="openai/gpt-oss-120b", help="model used for the translation")
    args = parser.parse_args()
    for meeting in args.meetings:
        if meeting not in MEETINGS:
            sys.exit(f"unknown meeting {meeting}; known: {', '.join(MEETINGS)}")
        build(meeting, translate=not args.no_translate, model=args.model)


if __name__ == "__main__":
    main()
