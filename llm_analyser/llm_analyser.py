import json, os, time, re
from dotenv import load_dotenv
from groq import Groq

module_dir = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

# Configuration from environment variables
GROQ_API_KEY_ENV = os.environ.get("GROQ_API_KEY_ENV")
GROQ_MODEL = os.environ.get("GROQ_MODEL")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS"))
BASE_BACKOFF_SECONDS = int(os.environ.get("BASE_BACKOFF_SECONDS"))

KLAYWERT_PROMPT = ("""
    You are an advanced AI model specializing in debate analysis, with extensive experience as a debate judge. Your task is to evaluate the performance of debaters in a structured debate. The speeches are in Brazilian Portuguese, and the input consists of text containing the debate instructions, along with the speeches of both debaters and the moderator. Each speech is labeled with the speaker’s identifier (e.g., "-MODERATOR: ..." or "-DEBATER 1: ..."). The moderator plays a key role in guiding the debate by posing questions that the debaters respond to. The theme of the debate is "Generative AI and its impacts on society.". Your goal is to analyze and evaluate the debaters based on their performance and assign an overall score. The response should include both the evaluation of debaters (written in english) and the overall scoring based on the evaluation criteria.

    Please think critically before responding.

    Instructions:
    • Analyze the provided text, which contains the speeches of debaters and the moderator;
    • Evaluate the performances of debaters based on the Evaluation Criteria section, but also based on their speeches, and considering their responses to the moderator’s questions. The performances analysis must be written in english;
    • Assign an individual overall score (in a 0-10 scale) to each debater, for each evaluation criteria provided.

    Evaluation Criteria:
    • Argumentation. Argumentation in a debate refers to the presentation of arguments, reasons, evidence, and logic to support a position or point of view in a structured discussion. It involves the skill of formulating solid and convincing 48 Chapter 4 - Methodology arguments that defend a thesis, opinion, or perspective to persuade the audience or debate participants. That includes: argument relevance, evidence, argument coherence and argument cohesion.
    • Persuasion. The skill of being persuasive in academic debates involves the ability of debaters to present their arguments and viewpoints in a compelling and convincing manner. It is the capacity to influence the beliefs, opinions, and decisions of the audience and, in some cases, the evaluators or judges. That includes: Eloquence and Convincingness.
    • Engagement. The skill of involvement and engagement in academic debates can be understood as the degree of a debater’s active participation and commitment to the discussion.
    • Adaptability. The skill of adaptability in academic debates refers to a debater’s ability to adjust and respond effectively to changing circumstances, including shifts in the debate’s dynamics, new arguments, questions or information, and the reactions of the audience or opponents. It is the capacity to be flexible and responsive during the debate.

    OUTPUT:
    All text provided in the response must be in english. The output is a .json format file, written in english, following the example below:a

    DEBATE:
    [text goes here]

    a the expected output example can be found in Appendix B
""")

DAVID_PROMPT = ("""
    You are an expert AI model specializing in computational linguistics and argument mining. Your task is to analyze an audio transcription of a semi-structured debate in Brazilian Portuguese and extract all argumentative components.

    Instructions:
    1. Identify all Arguments (Arg) present in the text.
    2. For each identified argument, extract its precise sub-components:
    - Premise (Prem): The underlying reasons or logic supporting the point.
    - Claim (Cla): The main assertion or thesis being defended.
    - Evidence (Evi): Concrete data, facts, or external quotes supporting the claim.

    OUTPUT:
    Return a strictly formatted JSON object in English containing the extracted components mapping to their original Brazilian Portuguese text spans.
""")

SYSTEM_PROMPT = ("""
    You are an expert debate judge and computational linguist specializing in
    argument mining and rhetorical analysis. Analyze a diarized Brazilian
    Portuguese debate transcript and return structured JSON.

    INPUT: turns with speaker, timestamp, text. May include a moderator
    guiding the debate via questions.

    LANGUAGE RULE: structural labels/field names in English. Free text
    extracted from the transcript (claim, premise, evidence, debate_summary,
    position change descriptions) stays in Brazilian Portuguese, original
    wording.

    ANALYZE PER TURN:
    1. Rhetoric: tag with ethos (credibility/authority), logos (logic/evidence),
    pathos (emotion/values). Multiple tags allowed.
    2. Argument mining: claim (main assertion), premise (reasoning behind
    claim), evidence (concrete facts/data/quotes, distinct from premise),
    relation_to_previous (support | attack | neutral).
    3. Fallacies: list any of [ad hominem, straw man, false dichotomy,
    appeal to authority, slippery slope, hasty generalization, red herring,
    circular reasoning]. Empty list if none.
    4. on_topic: boolean.

    ANALYZE PER SPEAKER (excluding moderator):
    5. Scores 0-10 each:
    - argumentation: argument quality, evidence, coherence, cohesion
    - persuasion: rhetorical effectiveness, eloquence, convincingness
    - engagement: active participation, responds to opponents/moderator
    - adaptability: adjusts to new arguments or shifts in the debate
    - topic_adherence: stays on topic
    6. rhetorical_profile: proportion of ethos/logos/pathos (0.0-1.0 each).
    7. fallacies_detected: list of fallacy types used by this speaker.
    8. position_changes: [{timestamp_s, description}] when speaker
    contradicts/revises a prior statement.
    9. engagement_metrics: {total_turns, total_words, avg_words_per_turn}.

    AGREEMENT MATRIX: pairwise agreement score 0.0 (disagree) to 1.0 (agree)
    between each pair of debaters.

    OUTPUT: valid JSON only, no markdown, no preamble. Schema:
    {turns: [{speaker, timestamp_s, text, rhetoric[], claim, premise,
    evidence, relation_to_previous, fallacies[], on_topic}],
    speakers: [{name, scores{argumentation,persuasion,engagement,
    adaptability,topic_adherence}, rhetorical_profile{ethos,logos,pathos},
    fallacies_detected[], position_changes[{timestamp_s,description}],
    engagement_metrics{total_turns,total_words,avg_words_per_turn}}],
    agreement_matrix{speaker:{speaker:score}}, debate_summary}
""")

USER_PROMPT_TEMPLATE = ("""
    Analyze the following transcript and return the requested JSON structure exactly as described:\n\n
    Transcript:\n{transcript_json}
""")


def build_transcript_json(transcript: dict) -> str:
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
                # response_format={"type": "json_object"},
                # max_tokens=MAX_TOKENS,
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


def analyze(transcript: dict) -> dict:
    """Analyze a diarized transcript and return structured argumentative analysis."""
    transcript_json = build_transcript_json(transcript)
    prompt = USER_PROMPT_TEMPLATE.format(transcript_json=transcript_json)
    raw_response = call_groq(prompt)

    try: parsed = json.loads(extract_json_from_response(raw_response))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Groq response as JSON") from exc

    return parsed