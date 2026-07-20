import os, re, json
from pathlib import Path


def get_participant_id_from_filepath(filepath: str, vad_timeline_path: str) -> str:
    """
    Extracts the speaking-element id from the transcript filename and
    looks up the matching participantName in the vad_timeline (or
    session events) JSON.
    """
    match = re.search(r"track_(.+)_transcription_segments\.json", filepath)

    if not match: raise ValueError(f"Could not extract element id from filepath: {filepath}")

    element_id = match.group(1)

    with open(vad_timeline_path, "r", encoding="utf-8") as f:
        timeline = json.load(f)

    for event in timeline["events"]:
        if event["data"]["participantName"] == element_id:
            return (f"{event["data"]["participantName"]}", f"{element_id.split("-")[-1]}")

    raise ValueError(f"No participant found for element participantName: {element_id}")


def get_speaker_info(filepath: str) -> tuple[str, list[dict]]:
    """
    Loads a Whisper output JSON file and keeps only id, text, start, end
    for each segment — discards tokens, words, temperature, avg_logprob,
    no_speech_prob. Returns (participant_name, segments).
    """
    with open(filepath, "r", encoding="utf-8") as f:
        segments = json.load(f)

    base_dir = Path(filepath).parent
    vad_timeline_pathfile = base_dir / "vad_timeline.json"
    participant_name, participant_id = get_participant_id_from_filepath(filepath, str(vad_timeline_pathfile))

    filtered_segments = [
        {
            "id": seg["id"],
            "text": seg["text"].strip(),
            "start": seg["start"],
            "end": seg["end"],
        }
        for seg in segments
    ]

    return participant_id, participant_name, filtered_segments


def get_all_speakers_info(path: str):
    all_info = {}
    
    for filename in os.listdir(path):
        match = re.search(r'track_(.*?)_transcription_segments\.json', filename)
        
        if match:
            speaker_id, speaker, segments_speaker = get_speaker_info(f"{path}/{filename}")
            all_info[speaker] = segments_speaker

    return all_info
