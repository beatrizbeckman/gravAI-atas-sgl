import json
import os
import subprocess
import time
from collections import defaultdict
from datetime import datetime

from gravai.models import ActionType, ParticipantData, Session, SessionDataDTO, Track, TrackInfoDTO


def _load_json_or_raise(path: str, label: str) -> dict:
    if not os.path.exists(path):
        raise RuntimeError(f"Missing {label} file: {path}")
    if os.path.getsize(path) == 0:
        raise RuntimeError(f"Empty {label} file: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {label} file: {path} ({exc})") from exc


def _wait_for_sidecar(sidecar_path: str, timeout_s: float = 120) -> dict:
    """The WS server writes the sidecar only after each track is closed and its WAV is
    re-encoded by ffmpeg, which happens a few seconds after the browser leaves."""
    deadline = time.time() + timeout_s
    while True:
        try:
            session_info = _load_json_or_raise(sidecar_path, "session sidecar")
        except RuntimeError:
            if time.time() >= deadline:
                raise
        else:
            tracks = session_info.get("tracks", {}).values()
            if all("ended_at" in track for track in tracks) or time.time() >= deadline:
                return session_info
        time.sleep(1)


def _extract_session_dto(slice_audio_tracks: str) -> SessionDataDTO:
    sidecar_path = os.path.join(slice_audio_tracks, "session_sidecar.json")
    vad_timeline_path = os.path.join(slice_audio_tracks, "vad_timeline.json")

    if not os.path.isdir(slice_audio_tracks):
        raise RuntimeError(
            f"Recording folder not found: {slice_audio_tracks}. "
            "No audio was received, so the bot probably never got into the meeting."
        )
    session_info = _wait_for_sidecar(sidecar_path)

    main_audio_track_name = None
    main_audio_track_name_sidecar_key = None
    for candidate_f in sorted(os.listdir(slice_audio_tracks)):
        if candidate_f.startswith("track_mainAudio") and candidate_f.endswith(".wav"):
            main_audio_track_name = candidate_f
            main_audio_track_name_sidecar_key = os.path.splitext(candidate_f)[0].replace("track_", "", 1)
            break
    if main_audio_track_name is None:
        raise RuntimeError(
            f"No 'track_mainAudio*.wav' file in {slice_audio_tracks}; the meeting audio was not captured."
        )

    vad_timeline = _load_json_or_raise(vad_timeline_path, "VAD timeline")
    if main_audio_track_name_sidecar_key not in session_info["tracks"]:
        raise RuntimeError(f"Track '{main_audio_track_name_sidecar_key}' is not listed in {sidecar_path}")

    session_data = SessionDataDTO(
        start_time=datetime.fromisoformat(session_info["tracks"][main_audio_track_name_sidecar_key]["started_at"]),
        end_time=datetime.fromisoformat(session_info["tracks"][main_audio_track_name_sidecar_key]["ended_at"]),
        main_track_name=main_audio_track_name,
        session_id=session_info["session_id"],
        events=[
            TrackInfoDTO(
                # action=ActionType.START if event["type"] == "start" else ActionType.END,
                participant_name=event["data"]["participantName"],
                element_id=event["data"]["id"],
                class_count=event["data"]["classCount"],
                timestamp=event["timestamp"],
            )
            for event in vad_timeline["events"]
        ],
    )
    return session_data


def _process_participant_data(session_data: SessionDataDTO):
    all_participants_data = defaultdict(list)
    for event in session_data.events:
        all_participants_data[event.element_id].append(
            {
                "class_count": event.class_count,
                "timestamp": event.timestamp,
                "participant_name": event.participant_name,
            }
        )
        # print(f"{event.timestamp} - {event.participant_name} - {event.element_id} - classCount={event.class_count}")
    return all_participants_data


def _find_participant_tracks(session_data: SessionDataDTO, all_participants_data: dict) -> dict:
    participants_tracks = {}
    for participant_id, participant_data in all_participants_data.items():
        class_counts = [event["class_count"] for event in participant_data]
        end_action = min(class_counts)
        start_action = max(class_counts)
        if start_action == end_action:
            # The speaking indicator never toggled: this participant never spoke.
            continue

        # Teams adds CSS classes to the voice-level outline while someone speaks, so the
        # highest class count means "speaking" and anything lower means "silent".
        track_changes = []
        for event in participant_data:
            time_in_s = datetime.fromtimestamp(event["timestamp"] / 1000).astimezone() - session_data.start_time
            is_speaking = event["class_count"] == start_action
            last_action = track_changes[-1][0] if track_changes else ActionType.END
            if is_speaking and last_action == ActionType.END:
                track_changes.append((ActionType.START, time_in_s))
            elif not is_speaking and last_action == ActionType.START:
                track_changes.append((ActionType.END, time_in_s))
        if not track_changes:
            continue
        if track_changes[-1][0] == ActionType.START:
            track_changes.append((ActionType.END, session_data.end_time - session_data.start_time))

        participants_tracks[participant_id] = track_changes

    return participants_tracks


def slice_audio_tracks(slice_audio_tracks: str):
    session_data = _extract_session_dto(slice_audio_tracks)
    all_participants_data = _process_participant_data(session_data)
    participants_tracks_locations = _find_participant_tracks(session_data, all_participants_data)
    session = create_session(slice_audio_tracks, session_data, all_participants_data, participants_tracks_locations)
    return session


def create_session(slice_audio_tracks, session_data, all_participants_data, participants_tracks_locations):
    participants_tracks = {}
    # Create an audio track that is the same size as the main track original and put zero audio outside of the desired track from the participant (so only the participant audio is present in the track, but it is aligned with the main track timeline)
    for participant_id, track_changes in participants_tracks_locations.items():
        participant_track_path = os.path.join(slice_audio_tracks, f"track_{participant_id}.wav")
        main_track_path = os.path.join(slice_audio_tracks, session_data.main_track_name)
        segments = []
        start_time = None
        for change in track_changes:
            if change[0] == ActionType.START:
                start_time = change[1].total_seconds()
            elif start_time is not None:
                end_time = change[1].total_seconds()
                segments.append((start_time, end_time))
                start_time = None

        if segments:
            active_expr = " + ".join(f"between(t,{start},{end})" for start, end in segments)
        else:
            active_expr = "0"

        filter_chain = ",".join(
            [
                "apad=pad_dur=2",
                f"volume=enable='{active_expr}':volume=1",
                f"volume=enable='not({active_expr})':volume=0",
            ]
        )

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            main_track_path,
            "-af",
            filter_chain,
            participant_track_path,
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        participants_tracks[participant_id] = ParticipantData(
            participant_id=participant_id,
            participant_name=all_participants_data[participant_id][0]["participant_name"] or participant_id,
            track=Track(wav_file_path=participant_track_path),
        )

    return Session(
        session_id=session_data.session_id,
        session_start=session_data.start_time,
        session_end=session_data.end_time,
        tracks=participants_tracks,
    )


class Slicer:
    @staticmethod
    def slice_teams_audio_track(audio_tracks_path: str) -> Session:
        return slice_audio_tracks(audio_tracks_path)

    @staticmethod
    def save_session_data(session: Session, output_path: str):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session.model_dump(), f, default=str, ensure_ascii=False, indent=2)
