import json, os, re

from handle_data.utils import save_analysis_to_file

from .utils import *
from handle_data.filter_participant_info import get_all_speakers_info

from llm_analyser.groq_config import *
from llm_analyser.prompts import *

def analyze_turns_only(chunk: list[dict]) -> dict:
    """
    Passada 1: extração local por turno (rhetoric, claim, premise,
    evidence, fallacies, on_topic). Recebe um chunk do transcript.
    """
    transcript_json = build_transcript_json(chunk)
    prompt = USER_PROMPT_TEMPLATE.format(transcript_json=transcript_json)
    raw_response = call_groq(prompt, TURN_ANALYSIS_SYSTEM_PROMPT)


    print("Analyzing turns")

    try:
        parsed = json.loads(extract_json_from_response(raw_response))
        print(parsed)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Groq response as JSON (turn analysis)") from exc

    return parsed


def aggregate_debate_analysis(all_turns: list[dict]) -> dict:
    """
    Passada 2: agregação global (scores, rhetorical_profile,
    fallacies_detected, position_changes, engagement_metrics,
    agreement_matrix, debate_summary). Recebe os turns já processados
    pela Passada 1, não o texto bruto.
    """
    turns_json = json.dumps(all_turns, ensure_ascii=False)
    prompt = f"Analyze the following already-processed turns and return the requested JSON structure:\n\n{turns_json}"
    raw_response = call_groq(prompt, AGGREGATION_SYSTEM_PROMPT)

    print("Aggregating debate analysis")

    try:
        parsed = json.loads(extract_json_from_response(raw_response))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Groq response as JSON (aggregation)") from exc

    return parsed


def analyze_full_debate(tracks_output_dir: str) -> dict:

    transcript = flatten_transcript(get_all_speakers_info(tracks_output_dir))

    """
    Analyzes a debate in two passes, stopping Pass 1 early if approaching
    the daily token budget, always reserving enough tokens to run Pass 2
    (aggregation) on whatever was successfully analyzed.
    """
    chunks = chunk_transcript(transcript, CHUNK_SIZE)

    total_chunks = len(chunks)
    total_turns = len(transcript)
    total_duration_s = transcript[-1]["start"] if transcript else 0.0

    tokens_used = 0
    budget_for_extraction = DAILY_TOKEN_BUDGET - RESERVED_FOR_AGGREGATION

    all_turns = []
    stopped_reason = None

    for i, chunk in enumerate(chunks):
        chunk_text = json.dumps(chunk, ensure_ascii=False)
        estimated_chunk_tokens = estimate_tokens(TURN_ANALYSIS_SYSTEM_PROMPT) + estimate_tokens(chunk_text)

        if tokens_used + estimated_chunk_tokens > budget_for_extraction:
            stopped_reason = "token_budget_reached"
            print(f"[warn] Stopping before chunk {i+1}/{total_chunks}: "
                  f"would exceed extraction budget ({tokens_used + estimated_chunk_tokens} > {budget_for_extraction})")
            break

        try:
            partial = analyze_turns_only(chunk)
            all_turns.extend(partial["turns"])
            tokens_used += estimated_chunk_tokens
        except Exception as exc:
            stopped_reason = "api_error"
            print(f"[warn] Chunk {i+1}/{total_chunks} failed: {exc}. Stopping early.")
            break

    # --- Coverage metrics ---
    analyzed_turns = len(all_turns)
    analyzed_duration_s = all_turns[-1]["timestamp_s"] if all_turns else 0.0
    coverage_pct = (analyzed_turns / total_turns * 100) if total_turns > 0 else 0.0

    def fmt_time(seconds) -> str:
        
        if isinstance(seconds, str):
            seconds = seconds.replace('s', '').replace('S', '').strip()
            
            if ':' in seconds:
                partes = seconds.split(':')
                if len(partes) == 2: 
                    seconds = int(partes[0]) * 60 + float(partes[1])
                elif len(partes) == 3: 
                    seconds = int(partes[0]) * 3600 + int(partes[1]) * 60 + float(partes[2])
        
        segundos_totais = float(seconds)
        
        m, s = divmod(int(segundos_totais), 60)
        return f"{m}:{s:02d}"

    coverage = {
        "turns_analyzed": analyzed_turns,
        "turns_total": total_turns,
        "duration_analyzed": fmt_time(analyzed_duration_s),
        "duration_total": fmt_time(total_duration_s),
        "coverage_pct": round(coverage_pct, 1),
        "tokens_used_estimated": tokens_used,
        "extraction_budget": budget_for_extraction,
        "stopped_early": stopped_reason is not None,
        "stopped_reason": stopped_reason,
        "label": (
            f"{analyzed_turns}/{total_turns} turns analyzed | "
            f"{fmt_time(analyzed_duration_s)}/{fmt_time(total_duration_s)} min | "
            f"{coverage_pct:.1f}% of debate analyzed"
        )
    }

    # --- Pass 2: always run on whatever was analyzed ---
    aggregated = {"speakers": [], "agreement_matrix": {}, "debate_summary": ""}
    if all_turns:
        try:
            aggregated = aggregate_debate_analysis(all_turns)
        except Exception as exc:
            print(f"[warn] Aggregation pass failed: {exc}. Returning partial result.")

    analysis = {
        "turns": all_turns,
        "speakers": aggregated.get("speakers", []),
        "agreement_matrix": aggregated.get("agreement_matrix", {}),
        "debate_summary": aggregated.get("debate_summary", ""),
        "coverage": coverage,
    }

    save_analysis_to_file(analysis, f"{tracks_output_dir}/analysis_result.json")

    return analysis
