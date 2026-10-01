"""
Orchestrates one minutes generation from start to end:

    template + header + utterances
        -> split transcript into parts that fit the LLM context
        -> one LLM call per part (with retries when the reply is unusable)
        -> merge call when there was more than one part
        -> .docx

This is what the jobs (and the CLI below) call. It knows nothing about HTTP.
Failures are raised as MinutesError with one of the error codes of the API
contract (docs/API_MINUTES.md, section 4.1).
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

import requests

from minutes import llm
from minutes.custom_template import CustomSpec, build_custom_template
from minutes.docx_writer import write_minutes
from minutes.prompt_builder import (
    DEFAULT_MAX_CHARS,
    ResponseValidationError,
    build_merge_prompt,
    build_system_prompt,
    build_user_prompt,
    parse_response,
    split_transcript,
)
from minutes.templates import MinutesTemplate, load_template
from models.models import Utterance

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LLM_RETRIES = 2  # extra attempts per prompt after the first one

LLMCallable = Callable[[str, str], str]
ProgressCallback = Callable[[str], None]


class MinutesError(Exception):
    """A generation failure with a stable code for the API (see contract 4.1)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class GenerationResult:
    template: MinutesTemplate
    header: dict
    participants: list[str]
    minutes: dict
    docx_path: str
    utterances: int
    parts: int
    llm_model: str
    generation_seconds: float
    llm_calls: int = 0
    retries: int = 0
    partials: list[dict] = field(default_factory=list, repr=False)


# ------------------------------------------------------------- resolution

def resolve_template(template_id: str, custom: CustomSpec | dict | None = None) -> MinutesTemplate:
    """Fixed templates come from the JSON files; 'custom' is built from the request spec."""
    if template_id == "custom":
        if custom is None:
            raise ValueError("template 'custom' needs the 'custom' object (instructions or sections)")
        spec = custom if isinstance(custom, CustomSpec) else CustomSpec.model_validate(custom)
        return build_custom_template(spec)
    if custom is not None:
        raise ValueError(f"'custom' is only accepted with template 'custom', not '{template_id}'")
    return load_template(template_id)


def missing_header_fields(template: MinutesTemplate, header: dict) -> list[str]:
    """Keys of required header fields that are absent or blank."""
    return [f.key for f in template.header if f.required and not str(header.get(f.key) or "").strip()]


def normalize_header(template: MinutesTemplate, header: dict) -> dict:
    """Keeps only the template's header keys, as stripped strings, applying defaults."""
    clean = {}
    for f in template.header:
        value = str(header.get(f.key) or "").strip()
        clean[f.key] = value or (f.default or "")
    return clean


def resolve_logo(template: MinutesTemplate) -> str | None:
    """minutes/assets/<logo>.(png|jpg|jpeg) when the template names a logo and the file exists."""
    if not template.logo:
        return None
    for ext in ("png", "jpg", "jpeg"):
        path = os.path.join(ASSETS_DIR, f"{template.logo}.{ext}")
        if os.path.isfile(path):
            return path
    return None


def suggest_filename(template_id: str, header: dict, when: time.struct_time | None = None) -> str:
    """ata_dell_2026-10-01_portal-de-suporte.docx"""
    date = time.strftime("%Y-%m-%d", when or time.localtime())
    project = _slug(str(header.get("projeto") or ""))
    return f"ata_{template_id}_{date}" + (f"_{project}" if project else "") + ".docx"


def _slug(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-")


# ------------------------------------------------------------- generation

def prepare_utterances(utterances: list[Utterance | dict]) -> list[Utterance]:
    """Drops blank or invalid turns and sorts chronologically."""
    clean = []
    for u in utterances:
        u = u if isinstance(u, Utterance) else Utterance(**u)
        text = " ".join(u.text.split())
        if text and u.end > u.start and u.speaker.strip():
            clean.append(Utterance(speaker=u.speaker.strip(), start=u.start, end=u.end, text=text))
    clean.sort(key=lambda u: (u.start, u.end, u.speaker))
    return clean


def generate_minutes(
    template_id: str,
    header: dict,
    utterances: list[Utterance | dict],
    output_path: str,
    participants: list[str] | None = None,
    custom: CustomSpec | dict | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    retries: int = LLM_RETRIES,
    progress: ProgressCallback | None = None,
    call_llm: LLMCallable | None = None,
) -> GenerationResult:
    """
    Runs the whole pipeline and writes the .docx to output_path.

    - participants: when None, the distinct speakers of the transcript, sorted.
    - progress: called with "generating" and "rendering" so a job can expose its stage.
    - call_llm: (system, user) -> reply text; defaults to minutes.llm.generate.
    Raises MinutesError(code) for expected failures and ValueError for bad input.
    """
    call_llm = call_llm or llm.generate
    report = progress or (lambda stage: None)
    started = time.monotonic()

    template = resolve_template(template_id, custom)
    missing = missing_header_fields(template, header)
    if missing:
        raise ValueError(f"missing required header fields for template '{template.id}': {', '.join(missing)}")
    header = normalize_header(template, header)

    utterances = prepare_utterances(utterances)
    if not utterances:
        raise MinutesError("empty_transcript", "the transcript has no usable utterances")
    participants = [p.strip() for p in participants if p.strip()] if participants else sorted({u.speaker for u in utterances})

    report("generating")
    system = build_system_prompt(template)
    parts = split_transcript(utterances, max_chars)
    calls = _CallCounter(call_llm)

    partials = []
    for i, part in enumerate(parts, 1):
        user = build_user_prompt(template, part, header, participants, part=(i, len(parts)) if len(parts) > 1 else None)
        partials.append(_ask(template, system, user, calls, retries))
    if len(partials) > 1:
        minutes = _ask(template, system, build_merge_prompt(template, partials, header, participants), calls, retries)
    else:
        minutes = partials[0]

    report("rendering")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    try:
        write_minutes(template, header, participants, minutes, output_path, resolve_logo(template))
    except Exception as exc:
        raise MinutesError("internal", f"could not write the .docx: {exc}") from exc

    return GenerationResult(
        template=template,
        header=header,
        participants=participants,
        minutes=minutes,
        docx_path=output_path,
        utterances=len(utterances),
        parts=len(parts),
        llm_model=llm.model_name(),
        generation_seconds=round(time.monotonic() - started, 1),
        llm_calls=calls.count,
        retries=calls.retries,
        partials=partials if len(partials) > 1 else [],
    )


class _CallCounter:
    def __init__(self, call_llm: LLMCallable):
        self._call = call_llm
        self.count = 0
        self.retries = 0

    def __call__(self, system: str, user: str) -> str:
        self.count += 1
        try:
            return self._call(system, user)
        except (requests.RequestException, RuntimeError) as exc:
            # llm.py turns connection/404/empty replies into RuntimeError; timeouts arrive as requests exceptions.
            raise MinutesError("llm_unreachable", str(exc)) from exc


def _ask(template: MinutesTemplate, system: str, user: str, call: _CallCounter, retries: int) -> dict:
    """
    One prompt -> parsed minutes. When the reply is not usable (bad JSON, empty
    required section) the prompt is sent again with the problems appended, so a
    deterministic model (temperature 0) does not simply repeat the same answer.
    """
    prompt = user
    last: ResponseValidationError | None = None
    for attempt in range(1 + retries):
        raw = call(system, prompt)
        try:
            return parse_response(template, raw)
        except ResponseValidationError as exc:
            last = exc
            call.retries += 1
            prompt = (
                f"{user}\n\nA resposta anterior foi rejeitada: {exc}. "
                "Responda novamente com um único objeto JSON válido, com todas as chaves do formato, "
                "preenchendo as seções obrigatórias com o que há na transcrição."
            )
    call.retries -= 1  # the last failure is not a retry, it is the final outcome
    raise MinutesError("llm_invalid_response", f"model reply unusable after {1 + retries} attempts: {last}")


# -------------------------------------------------------------------- CLI

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a .docx from a fixture (template, header, utterances) through the configured LLM")
    parser.add_argument("fixture", help="JSON like minutes/tests/fixtures/reuniao_dell.json")
    parser.add_argument("-o", "--output", help="output .docx (default: ata_<template>_<date>_<projeto>.docx)")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="transcript characters per LLM request before splitting")
    parser.add_argument("--json", action="store_true", help="also print the minutes JSON")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(args.fixture, encoding="utf-8") as f:
        fixture = json.load(f)
    output = args.output or suggest_filename(fixture["template"], fixture["header"])

    try:
        result = generate_minutes(
            fixture["template"], fixture["header"], fixture["utterances"], output,
            participants=fixture.get("participants"), custom=fixture.get("custom"), max_chars=args.max_chars,
            progress=lambda stage: print(f"[{stage}]", file=sys.stderr),
        )
    except MinutesError as exc:
        print(f"error ({exc.code}): {exc.message}", file=sys.stderr)
        sys.exit(1)

    print(f"{result.docx_path}  ({result.utterances} utterances, {result.parts} part(s), {result.llm_calls} LLM call(s), "
          f"{result.retries} retry(ies), {result.generation_seconds}s, model {result.llm_model})")
    if args.json:
        print(json.dumps(result.minutes, ensure_ascii=False, indent=2))
