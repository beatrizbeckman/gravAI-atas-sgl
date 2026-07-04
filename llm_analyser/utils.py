import json, os, re
from dotenv import load_dotenv

load_dotenv()

# Configuration from environment variables
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE"))
DAILY_TOKEN_BUDGET = int(os.environ.get("DAILY_TOKEN_BUDGET"))
RESERVED_FOR_AGGREGATION = int(os.environ.get("RESERVED_FOR_AGGREGATION"))


def build_transcript_json(transcript: dict) -> str: return json.dumps(transcript, ensure_ascii=False, indent=2)


def extract_json_from_response(raw_response: str) -> str:
    """
    Removes <think>...</think> reasoning blocks and markdown code fences
    from the LLM response, returning only the JSON content.
    """
    # Remove <think>...</think> block
    cleaned = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL)

    # Extract content inside ```json ... ``` if present
    match = re.search(r"```json\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if match:
        return match.group(1)

    # Fallback: try to find the first { to last } in case there's no fence
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match: return match.group(0)

    return cleaned.strip()


def chunk_transcript(transcript: list[dict], chunk_size: int) -> list[list[dict]]:
    """
    Splits a flat, chronologically-ordered transcript into chunks for
    sequential LLM processing in Passada 1 (turn-level analysis).

    Each chunk is a list of turn dicts (speaker, t/start, text, ...).
    Chunking avoids hitting the LLM's TPM/context limits on long debates;
    cross-chunk context (scores, agreement_matrix, position_changes) is
    handled separately by the aggregation pass (Passada 2), not here.
    """
    if chunk_size <= 0: raise ValueError("chunk_size must be a positive integer")

    return [
        transcript[i:i + chunk_size]
        for i in range(0, len(transcript), chunk_size)
    ]


def flatten_transcript(grouped_transcript: dict[str, list[dict]]) -> list[dict]:
    """
    Converts a {speaker_name: [segments]} dict into a flat,
    chronologically-ordered list of turns with speaker embedded,
    ready for chunk_transcript / analyze_full_debate.
    """
    flat = []
    for speaker, segments in grouped_transcript.items():
        for seg in segments:
            flat.append({**seg, "speaker": speaker})

    return sorted(flat, key=lambda t: t["start"])
