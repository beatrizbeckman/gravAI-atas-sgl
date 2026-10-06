"""
Runs the minutes pipeline over a set of transcripts with a list of models and
records everything needed to compare them: the exact prompts, the raw replies,
the parsed minutes, the .docx, time, tokens and estimated cost.

Usage
    uv run python experiments/run_experiments.py
    uv run python experiments/run_experiments.py --models groq:openai/gpt-oss-20b groq:openai/gpt-oss-120b
    uv run python experiments/run_experiments.py --transcripts datasets/reunioes/ES2004a/transcricao.json
    uv run python experiments/run_experiments.py --out experiments/results/2026-10-07_reuniao

A model is "<provider>:<model id>". Providers and the .env variable holding
their key are in PROVIDERS below. Prices per million tokens come from
experiments/precos.json (edit it when a provider changes prices; unknown models
get cost "n/d").

Output: <out>/<transcript>__<provider>__<model>/ with
    prompts/NN_system.txt, NN_user.txt, NN_raw.txt   one trio per LLM call
    minutes.json                                     parsed minutes (when it worked)
    ata.docx                                         rendered minutes (when it worked)
    meta.json                                        model, times, tokens, cost, error
and <out>/resumo.csv + <out>/resumo.md with one line per (transcript, model),
with an empty "nota" column to be filled by hand after reading the minutes.

Pointing --out at an existing run resumes it: pairs whose meta.json says "ok"
are skipped, the others are rerun, and the summary covers every pair found in
the folder (so a batch can be extended with new models or transcripts later).
Notes and observations already typed into meta.json are kept.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from gravai.minutes import llm
from gravai.minutes.dataset import list_meetings, read_json, transcript_path, write_json, write_text
from gravai.minutes.generate import DEFAULT_MAX_CHARS, MinutesError, generate_minutes

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# provider -> (base url, name of the .env variable with the key)
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ"),
    "deepinfra": ("https://api.deepinfra.com/v1/openai", "DEEP_INFRA"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}

DEFAULT_MODELS = [
    "groq:openai/gpt-oss-20b",
    "groq:qwen/qwen3.8-27b",
    "groq:openai/gpt-oss-120b",
]

DEFAULT_TRANSCRIPTS = [transcript_path(meeting_id) for meeting_id in list_meetings()]


def load_prices() -> dict:
    path = os.path.join(HERE, "precos.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def transcript_label(path: str) -> str:
    folder = os.path.basename(os.path.dirname(path))
    return folder if os.path.basename(path) == "transcricao.json" else os.path.splitext(os.path.basename(path))[0]


def safe(name: str) -> str:
    return name.replace("/", "-").replace(":", "-")


class Recorder:
    """The call_llm handed to generate_minutes: calls one model directly and logs each call."""

    def __init__(
        self, base_url: str, api_key: str, model: str, timeout: int, folder: str, max_tokens: int, extra: dict | None
    ):
        self.cfg = {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "timeout": timeout,
            "max_tokens": max_tokens,
            "extra": extra or None,
        }
        self.folder = os.path.join(folder, "prompts")
        os.makedirs(self.folder, exist_ok=True)
        self.calls: list[dict] = []

    def __call__(self, system: str, user: str) -> str:
        n = len(self.calls) + 1
        try:
            reply = llm.openai_chat_retrying(
                system, user, log=lambda msg: print(f"      call {n}: {msg}", flush=True), **self.cfg
            )
        except RuntimeError as exc:
            self._write(n, system, user, f"<<ERROR>> {exc}")
            raise
        self._write(n, system, user, reply.content)
        usage = reply.usage
        self.calls.append(
            {
                "n": n,
                "seconds": reply.seconds,
                "json_mode": reply.json_mode,
                "finish_reason": reply.finish_reason,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                "system_chars": len(system),
                "user_chars": len(user),
                "reply_chars": len(reply.content),
            }
        )
        return reply.content

    def _write(self, n: int, system: str, user: str, raw: str):
        for suffix, text in (("system", system), ("user", user), ("raw", raw)):
            with open(os.path.join(self.folder, f"{n:02d}_{suffix}.txt"), "w", encoding="utf-8") as f:
                f.write(text)

    def totals(self) -> dict:
        def total(key):
            values = [c[key] for c in self.calls if c[key] is not None]
            return sum(values) if values else None

        return {
            "llm_calls": len(self.calls),
            "llm_seconds": round(sum(c["seconds"] for c in self.calls), 2),
            "prompt_tokens": total("prompt_tokens"),
            "completion_tokens": total("completion_tokens"),
            "reasoning_tokens": total("reasoning_tokens"),
            "json_mode_fallbacks": sum(1 for c in self.calls if not c["json_mode"]),
            "truncated_replies": sum(1 for c in self.calls if c["finish_reason"] == "length"),
        }


def estimate_cost(prices: dict, model: str, prompt_tokens, completion_tokens):
    p = prices.get(model)
    if not p or prompt_tokens is None or completion_tokens is None:
        return None
    return round((prompt_tokens * p["input_per_m"] + completion_tokens * p["output_per_m"]) / 1_000_000, 5)


def run_folder(out_dir: str, transcript_path: str, provider: str, model: str) -> str:
    return os.path.join(out_dir, f"{transcript_label(transcript_path)}__{provider}__{safe(model)}")


def previous_meta(folder: str) -> dict | None:
    path = os.path.join(folder, "meta.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


def run_one(
    transcript_path: str,
    provider: str,
    model: str,
    out_dir: str,
    timeout: int,
    max_chars: int,
    prices: dict,
    max_tokens: int,
    extra: dict | None,
) -> dict:
    label = transcript_label(transcript_path)
    folder = run_folder(out_dir, transcript_path, provider, model)
    previous = previous_meta(folder)
    if previous and previous.get("status") == "ok":
        print(f"  {label} x {provider}:{model} · already ok, skipped", flush=True)
        return previous
    os.makedirs(folder, exist_ok=True)

    fixture = read_json(transcript_path)
    base_url, key_env = PROVIDERS[provider]
    api_key = os.environ.get(key_env, "")
    recorder = Recorder(base_url, api_key, model, timeout, folder, max_tokens, extra)

    meta = {
        "transcript": label,
        "transcript_path": os.path.relpath(transcript_path, ROOT),
        "gabarito": _gabarito_for(transcript_path),
        "template": fixture["template"],
        "utterances": len(fixture["utterances"]),
        "transcript_chars": sum(len(u["text"]) for u in fixture["utterances"]),
        "provider": provider,
        "model": model,
        "max_chars": max_chars,
        "max_tokens": max_tokens,
        "extra": extra,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": None,
        "error_code": None,
        "error": None,
        "nota": previous.get("nota") if previous else None,
        "observacoes": previous.get("observacoes", "") if previous else "",
    }
    print(f"  {label} x {provider}:{model}", flush=True)
    started = time.monotonic()
    try:
        result = generate_minutes(
            fixture["template"],
            fixture["header"],
            fixture["utterances"],
            output_path=os.path.join(folder, "ata.docx"),
            participants=fixture.get("participants"),
            custom=fixture.get("custom"),
            max_chars=max_chars,
            call_llm=recorder,
        )
        meta.update(status="ok", parts=result.parts, retries=result.retries)
        write_json(os.path.join(folder, "minutes.json"), result.minutes)
        meta["filled_sections"] = sum(
            1 for v in result.minutes.values() if v not in ("", [], {}, None) and not _empty_record(v)
        )
        meta["total_sections"] = len(result.minutes)
    except MinutesError as exc:
        meta.update(status="failed", error_code=exc.code, error=exc.message, parts=None, retries=None)
    except Exception as exc:
        meta.update(
            status="crashed", error_code="exception", error=f"{type(exc).__name__}: {exc}", parts=None, retries=None
        )

    meta["total_seconds"] = round(time.monotonic() - started, 2)
    meta.update(recorder.totals())
    meta["cost_usd"] = estimate_cost(prices, model, meta["prompt_tokens"], meta["completion_tokens"])
    meta["calls"] = recorder.calls
    write_json(os.path.join(folder, "meta.json"), meta)
    status = meta["status"] + (f" ({meta['error_code']})" if meta["error_code"] else "")
    print(
        f"      {status} · {meta['total_seconds']}s · {meta['llm_calls']} call(s) · tokens {meta['prompt_tokens']}+{meta['completion_tokens']}",
        flush=True,
    )
    return meta


def _gabarito_for(transcript_path: str) -> str | None:
    candidate = os.path.join(os.path.dirname(transcript_path), "gabarito.md")
    return os.path.relpath(candidate, ROOT) if os.path.exists(candidate) else None


def _empty_record(value) -> bool:
    return isinstance(value, dict) and all(v in ("", None, []) for v in value.values())


COLUMNS = [
    "transcript",
    "template",
    "utterances",
    "transcript_chars",
    "provider",
    "model",
    "status",
    "error_code",
    "parts",
    "llm_calls",
    "retries",
    "json_mode_fallbacks",
    "truncated_replies",
    "total_seconds",
    "llm_seconds",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "cost_usd",
    "filled_sections",
    "total_sections",
    "nota",
    "observacoes",
]


def all_metas(out_dir: str) -> list[dict]:
    """Every pair recorded in the run folder, including ones from earlier invocations."""
    rows = []
    for path in sorted(glob.glob(os.path.join(out_dir, "*", "meta.json"))):
        rows.append(read_json(path))
    rows.sort(key=lambda r: (r["provider"], r["model"], r["transcript"]))
    return rows


def write_summary(out_dir: str, rows: list[dict]):
    with open(os.path.join(out_dir, "resumo.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Resumo dos experimentos",
        "",
        f"Gerado em {datetime.now():%d/%m/%Y %H:%M}. Pasta: `{os.path.relpath(out_dir, ROOT)}`.",
        "",
        "| Transcrição | Falas | Modelo | Status | Partes | Chamadas | Tempo (s) | Tokens in+out | Custo (US$) | Seções preenchidas | Nota |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        status = r["status"] + (f" `{r['error_code']}`" if r["error_code"] else "")
        tokens = f"{r['prompt_tokens']}+{r['completion_tokens']}" if r["prompt_tokens"] is not None else "n/d"
        cost = f"{r['cost_usd']:.4f}" if r["cost_usd"] is not None else "n/d"
        filled = f"{r.get('filled_sections')}/{r.get('total_sections')}" if r.get("total_sections") else ""
        lines.append(
            f"| {r['transcript']} | {r['utterances']} | {r['provider']}:{r['model']} | {status} | {r['parts'] or ''} | "
            f"{r['llm_calls']} | {r['total_seconds']} | {tokens} | {cost} | {filled} | {r['nota'] or ''} |"
        )
    lines += [
        "",
        "Nota: 1 a 5, preenchida à mão comparando `minutes.json` com o `gabarito.md` da transcrição.",
        "Critérios: decisões capturadas, pendências com responsável, nada inventado, JSON válido de primeira.",
    ]
    write_text(os.path.join(out_dir, "resumo.md"), "\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--transcripts",
        nargs="*",
        default=DEFAULT_TRANSCRIPTS,
        help="transcript JSONs (default: every datasets/reunioes/*/transcricao.json)",
    )
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS, help="provider:model (default: %(default)s)")
    parser.add_argument("--out", default=os.path.join(HERE, "results", datetime.now().strftime("%Y-%m-%d_%H%M")))
    parser.add_argument("--timeout", type=int, default=180, help="seconds per LLM request")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="transcript characters per LLM request before splitting",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=8000, help="reply cap per LLM request (reasoning tokens count)"
    )
    parser.add_argument(
        "--extra", default=None, help='JSON merged into every request, e.g. \'{"reasoning_effort": "low"}\''
    )
    args = parser.parse_args()
    extra = json.loads(args.extra) if args.extra else None

    for m in args.models:
        provider = m.split(":", 1)[0]
        if provider not in PROVIDERS:
            sys.exit(f"unknown provider '{provider}' in {m}; known: {', '.join(PROVIDERS)}")
        if not os.environ.get(PROVIDERS[provider][1]):
            sys.exit(f"missing .env variable {PROVIDERS[provider][1]} for provider {provider}")

    os.makedirs(args.out, exist_ok=True)
    prices = load_prices()
    print(f"{len(args.transcripts)} transcript(s) x {len(args.models)} model(s) -> {args.out}", flush=True)
    for m in args.models:
        provider, model = m.split(":", 1)
        for path in args.transcripts:
            run_one(path, provider, model, args.out, args.timeout, args.max_chars, prices, args.max_tokens, extra)
            write_summary(
                args.out, all_metas(args.out)
            )  # rewritten after every run, so a stopped batch still has its table
    print(f"\nresumo: {os.path.join(args.out, 'resumo.md')}")


if __name__ == "__main__":
    main()
