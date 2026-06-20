import json, os, time, re
from dotenv import load_dotenv
from groq import Groq

module_dir = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

# Configuration from environment variables
GROQ_API_KEY_ENV = os.environ.get("GROQ_API_KEY_ENV")
GROQ_MODEL = os.environ.get("GROQ_MODEL")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES"))
BASE_BACKOFF_SECONDS = int(os.environ.get("BASE_BACKOFF_SECONDS"))

SYSTEM_PROMPT = (
    """You are an advanced AI model specializing in debate analysis and rhetorical theory, with extensive experience as a debate judge and computational linguist.

    Your task is to analyze a debate transcript in Brazilian Portuguese and return a structured JSON analysis. Think critically before responding.

    ## INPUT
    You will receive a diarized debate transcript: each turn contains a speaker name, timestamp, and spoken text.

    ## ANALYSIS DIMENSIONS

    ### 1. Rhetorical Classification (per turn)
    Classify each turn using classical rhetoric:
    - **Ethos**: appeal to credibility, authority, character or trustworthiness
    - **Logos**: appeal to logic, evidence, data, reasoning or structured argumentation
    - **Pathos**: appeal to emotion, empathy, fear, pride or moral values
    - A turn may contain more than one type.

    ### 2. Argument Structure (per turn)
    Based on DEBISS-Arg annotation protocol:
    - **claim**: the main assertion being made
    - **premise**: evidence or reasoning supporting the claim
    - **relation_to_previous**: one of [support, attack, neutral]

    ### 3. Fallacy Detection (per turn)
    Identify if any of the following are present:
    - Ad hominem, straw man, false dichotomy, appeal to authority, slippery slope, hasty generalization, red herring, circular reasoning
    - If none detected, return empty list.

    ### 4. Debater Evaluation (per speaker, 0–10 scale)
    Score each debater on:
    - **argumentation**: quality of claims, premises and logical structure
    - **persuasion**: effective use of ethos/logos/pathos
    - **engagement**: directly addresses opponent's arguments
    - **adaptability**: adjusts position or strategy during the debate
    - **topic_adherence**: stays on the debate topic throughout

    ### 5. Engagement Metrics (per speaker)
    - total_turns: number of speaking turns
    - total_words: approximate word count
    - avg_words_per_turn: average length of contributions
    - position_changes: moments where the speaker contradicts or revises a prior statement

    ### 6. Agreement Matrix
    For each pair of speakers, estimate a agreement score from 0.0 (full disagreement) to 1.0 (full agreement).

    ## OUTPUT FORMAT
    Respond ONLY with a valid JSON object, in brazilian portuguese. No markdown, no explanation, no preamble.

    ```json
    {
    "turns": [
        {
        "speaker": "string",
        "timestamp_s": 0.0,
        "text": "string",
        "rhetoric": ["ethos", "logos", "pathos"],
        "claim": "string or null",
        "premise": "string or null",
        "relation_to_previous": "support | attack | neutral",
        "fallacies": ["string"],
        "on_topic": true
        }
    ],
    "speakers": [
        {
        "name": "string",
        "scores": {
            "argumentation": 0.0,
            "persuasion": 0.0,
            "engagement": 0.0,
            "adaptability": 0.0,
            "topic_adherence": 0.0
        },
        "rhetorical_profile": {
            "ethos": 0.0,
            "logos": 0.0,
            "pathos": 0.0
        },
        "fallacies_detected": ["string"],
        "position_changes": [
            { "timestamp_s": 0.0, "description": "string" }
        ],
        "engagement_metrics": {
            "total_turns": 0,
            "total_words": 0,
            "avg_words_per_turn": 0.0
        }
        }
    ],
    "agreement_matrix": {
        "Speaker A": { "Speaker B": 0.0 }
    },
    "debate_summary": "string"
    }
    ```
    """
)

USER_PROMPT_TEMPLATE = (
    "Analyze the following transcript and return the requested JSON structure exactly as described:\n\n"
    "Transcript:\n{transcript_json}"
)


def build_transcript_json(transcript: list[dict]) -> str:
    return json.dumps(transcript, ensure_ascii=False, indent=2)


def create_groq_client() -> Groq:
    api_key = GROQ_API_KEY_ENV
    if not api_key:
        raise RuntimeError("Missing environment variable: GROQ_API_KEY")
    return Groq(api_key=api_key)


def call_groq(prompt: str) -> str:
    client = create_groq_client()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )

            content_text = response.choices[0].message.content
            if not content_text or not content_text.strip():
                raise RuntimeError("Groq response content is empty")

            return content_text

        except Exception as exc:
            if attempt >= MAX_RETRIES:
                raise RuntimeError(f"Groq API request failed after {MAX_RETRIES} attempts: {exc}") from exc
            backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            time.sleep(backoff)


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
    if match:
        return match.group(0)

    return cleaned.strip()


def analyze(transcript: list[dict]) -> dict:
    """Analyze a diarized transcript and return structured argumentative analysis."""
    transcript_json = build_transcript_json(transcript)
    prompt = USER_PROMPT_TEMPLATE.format(transcript_json=transcript_json)
    raw_response = call_groq(prompt)

    try:
        parsed = json.loads(extract_json_from_response(raw_response))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Groq response as JSON") from exc

    return parsed