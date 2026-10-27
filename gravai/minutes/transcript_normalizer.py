import argparse
import json
import os
import re
from difflib import SequenceMatcher

from gravai.legacy.handle_data.filter_participant_info import get_all_speakers_info
from gravai.models import Utterance

SESSION_TRANSCRIPTION_FILE = "session_transcription.json"

# Text whisper produces on silence or noise: subtitle credits, channel outros,
# sound tags like [Música] and segments made only of punctuation.
HALLUCINATION_PATTERN = re.compile(
    r"amara\.org|legenda(s|do)? pela comunidade|legendas? por|obrigad[oa] por assistir|"
    # a subtitle credit with a name and nothing else, e.g. "Legenda Adriana Zanotto"
    r"^legendas?:? \S+( \S+){0,3}\.?$|"
    r"inscreva-se|se inscreva|curta e compartilhe|^[\[\(].*[\]\)]$|^\W+$",
    re.IGNORECASE,
)


def load_session_segments(tracks_dir: str) -> dict[str, list[dict]]:
    """
    Returns {speaker_name: raw whisper segments} for a recording folder.

    Uses session_transcription.json (written by /transcribe) when present. The
    paths inside it are container paths (/app/tmp/...), so when they do not
    exist as written they are resolved by file name against tracks_dir.
    """
    path = os.path.join(tracks_dir, SESSION_TRANSCRIPTION_FILE)
    if not os.path.isfile(path):
        # Older recordings only have the per-track files; names come from the VAD timeline.
        return get_all_speakers_info(tracks_dir)

    with open(path, encoding="utf-8") as f:
        session = json.load(f)

    speakers = {}
    for participant_id, participant in session["tracks"].items():
        segments_path = participant["transcription"]["transcription_segments_file_path"]
        if not os.path.isfile(segments_path):
            segments_path = os.path.join(tracks_dir, os.path.basename(segments_path))
        with open(segments_path, encoding="utf-8") as f:
            segments = json.load(f)

        name = participant.get("participant_name") or participant_id
        # Two participants can share a display name; keep both instead of overwriting.
        key = name if name not in speakers else f"{name} ({participant_id})"
        speakers[key] = segments

    return speakers


def normalize_segments(
    speaker_segments: dict[str, list[dict]],
    no_speech_threshold: float = 0.6,
    merge_gap_s: float | None = 1.0,
    duplicate_similarity: float = 0.8,
) -> list[Utterance]:
    """
    Merges per-speaker whisper segments into a single chronological transcript.

    Every participant track is the full meeting audio with everyone else muted,
    so timestamps from different tracks share the same origin (session start)
    and can simply be sorted together.

    Cleaning, in order:
      - drop empty text, non-positive duration, no_speech_prob above the
        threshold and text matching HALLUCINATION_PATTERN;
      - drop the same phrase repeated back to back by one speaker (whisper
        loops on the muted stretches of a track);
      - when two speakers overlap in time saying (almost) the same thing, keep
        only one of them, see _drop_overlap_duplicates;
      - join consecutive segments of the same speaker when the pause between
        them is at most merge_gap_s (None keeps the whisper segments as they are).
    """
    utterances = []
    for speaker, segments in speaker_segments.items():
        for seg in segments:
            text = " ".join(seg.get("text", "").split())
            start, end = float(seg["start"]), float(seg["end"])
            if not text or end <= start or HALLUCINATION_PATTERN.search(text):
                continue
            # Whisper's own estimate of "there was no speech here" is the cheapest signal we have.
            if seg.get("no_speech_prob", 0.0) > no_speech_threshold:
                continue
            utterances.append(Utterance(speaker=speaker, start=round(start, 2), end=round(end, 2), text=text))

    utterances.sort(key=lambda u: (u.start, u.end, u.speaker))
    utterances = _drop_repeated(utterances)
    utterances = _drop_overlap_duplicates(utterances, duplicate_similarity)

    if merge_gap_s is None:
        return utterances
    return _merge_turns(utterances, merge_gap_s)


def _drop_repeated(utterances: list[Utterance]) -> list[Utterance]:
    kept: list[Utterance] = []
    for u in utterances:
        last = kept[-1] if kept else None
        if last and last.speaker == u.speaker and last.text.lower() == u.text.lower():
            continue
        kept.append(u)
    return kept


def _drop_overlap_duplicates(utterances: list[Utterance], min_similarity: float) -> list[Utterance]:
    """
    Speech that falls inside the VAD windows of two participants is present in
    both tracks and gets transcribed twice. The longer of the two is kept: the
    window of the real speaker normally covers the whole phrase, the other one
    only caught a slice of it. Attribution is a guess; proper diarization is
    the real fix.
    """
    kept: list[Utterance] = []
    for u in utterances:
        for i, k in enumerate(kept):
            if k.speaker != u.speaker and k.end > u.start and _same_speech(k, u, min_similarity):
                if u.end - u.start > k.end - k.start:
                    kept[i] = u
                break
        else:
            kept.append(u)
    kept.sort(key=lambda u: (u.start, u.end, u.speaker))
    return kept


def _same_speech(a: Utterance, b: Utterance, min_similarity: float) -> bool:
    overlap = min(a.end, b.end) - max(a.start, b.start)
    shortest = min(a.end - a.start, b.end - b.start)
    if overlap <= 0 or overlap / shortest < 0.5:
        return False
    # The copy on the other track is usually a piece of the phrase, so measure how
    # much of the shorter text is found in the longer one instead of a global ratio.
    short, long = sorted((a.text.lower(), b.text.lower()), key=len)
    matched = sum(block.size for block in SequenceMatcher(None, short, long).get_matching_blocks())
    return matched / len(short) >= min_similarity


def _merge_turns(utterances: list[Utterance], merge_gap_s: float) -> list[Utterance]:
    merged: list[Utterance] = []
    for u in utterances:
        last = merged[-1] if merged else None
        if last and last.speaker == u.speaker and u.start - last.end <= merge_gap_s:
            last.end = max(last.end, u.end)
            last.text = f"{last.text} {u.text}"
        else:
            merged.append(u)
    return merged


def normalize_session(tracks_dir: str, **kwargs) -> list[Utterance]:
    return normalize_segments(load_session_segments(tracks_dir), **kwargs)


def save_transcript(utterances: list[Utterance], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([u.model_dump() for u in utterances], f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Merge the per-participant whisper output of a recording into one transcript"
    )
    parser.add_argument("tracks_dir", help="recording folder (the *_tracks directory)")
    parser.add_argument("-o", "--output", help="write the transcript as JSON to this file")
    parser.add_argument("--no-merge", action="store_true", help="keep whisper segments as they are")
    args = parser.parse_args()

    transcript = normalize_session(args.tracks_dir, merge_gap_s=None if args.no_merge else 1.0)

    if args.output:
        save_transcript(transcript, args.output)
        print(f"{len(transcript)} utterances -> {args.output}")
    else:
        for u in transcript:
            print(f"[{u.start:8.2f} - {u.end:8.2f}] {u.speaker}: {u.text}")
