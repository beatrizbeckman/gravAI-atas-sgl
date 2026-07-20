import os
import json
from datetime import datetime
import subprocess
from models.models import (
    SessionDataDTO,
    TrackInfoDTO,
    ActionType,
    ParticipantData,
    Track,
    Session
)
from collections import defaultdict
import time

from config.logging_config import get_logger

# The session sidecar is written by the ws audio server process only after it
# finishes re-encoding the recorded track (ffmpeg pitch correction), which for
# long meetings can take well over a second after the browser/session ends.
_FILE_WAIT_TIMEOUT_S = 120.0
_FILE_WAIT_POLL_INTERVAL_S = 0.5


def _wait_for_file(path: str, label: str, log_dir: str, timeout: float = _FILE_WAIT_TIMEOUT_S) -> None:
    if os.path.exists(path):
        return
    logger = get_logger("slicing", log_dir)
    logger.info(f"Waiting for {label} file to be written: {path}")
    deadline = time.time() + timeout
    while not os.path.exists(path):
        if time.time() >= deadline:
            raise RuntimeError(f"Missing {label} file: {path}")
        time.sleep(_FILE_WAIT_POLL_INTERVAL_S)
    logger.info(f"{label} file is now available: {path}")


def _load_json_or_raise(path: str, label: str) -> dict:
    if not os.path.exists(path):
        raise RuntimeError(f"Missing {label} file: {path}")
    if os.path.getsize(path) == 0:
        raise RuntimeError(f"Empty {label} file: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {label} file: {path} ({exc})") from exc


def _extract_session_dto(slice_audio_tracks: str) -> SessionDataDTO:
    sidecar_path = os.path.join(slice_audio_tracks, "session_sidecar.json")
    vad_timeline_path = os.path.join(slice_audio_tracks, "vad_timeline.json")
    main_audio_track_path = None
    main_audio_track_name = None
    main_audio_track_name_sidecar_key = None
    for candidate_f in os.listdir(slice_audio_tracks):
        if candidate_f.startswith("track_mainAudio"):
            main_audio_track_path = os.path.join(slice_audio_tracks, candidate_f)
            main_audio_track_name = candidate_f
            main_audio_track_name_sidecar_key = candidate_f[:candidate_f.find(".")].replace("track_", "")
            break

    _wait_for_file(sidecar_path, "session sidecar", slice_audio_tracks)
    _wait_for_file(vad_timeline_path, "VAD timeline", slice_audio_tracks)
    assert main_audio_track_path is not None

    session_info = _load_json_or_raise(sidecar_path, "session sidecar")
    vad_timeline = _load_json_or_raise(vad_timeline_path, "VAD timeline")

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
            ) for event in vad_timeline["events"]
        ],
    )
    return session_data

def _process_participant_data(session_data: SessionDataDTO, group_slices_by_name: bool = True) -> dict:
    all_participants_data = defaultdict(list)
    logger = get_logger("slicing")
    logger.info(f"Slicing participants data for session {session_data.session_id} (group_slices_by_name={group_slices_by_name})")
    for event in session_data.events:
        target_key = event.participant_name if group_slices_by_name else event.element_id
        all_participants_data[target_key].append({
            "class_count": event.class_count,
            "timestamp": event.timestamp,
            "participant_name": event.participant_name,
        })
        # print(f"{event.timestamp} - {event.participant_name} - {event.element_id} - classCount={event.class_count}")

    logger.info(f"Sliced {len(all_participants_data)} participants data for session {session_data.session_id}")
    return all_participants_data

def _find_participant_tracks(session_data: SessionDataDTO, all_participants_data: dict) -> dict:
    participants_tracks = {}
    for participant_id, participant_data in all_participants_data.items():
        class_counts = [event["class_count"] for event in participant_data]
        end_action = min(class_counts)
        start_action = max(class_counts)
        assert len([c for c in class_counts if c == end_action or c == start_action]) == len(class_counts), "Expected only two distinct class counts per participant, representing start and end actions."

        track_changes = []
        for event in participant_data:
            time_in_s = datetime.fromtimestamp(event["timestamp"] / 1000).astimezone() - session_data.start_time
            print(time_in_s)
            if len(track_changes) == 0:
                if event["class_count"] == start_action:

                    
                    track_changes.append((ActionType.START, time_in_s))
            else:
                last_change = track_changes[-1]
                if event["class_count"] == end_action and last_change[0] == ActionType.START:
                    track_changes.append((ActionType.END, time_in_s))
        if track_changes[-1][0] == ActionType.START:
            track_changes.append((ActionType.END, session_data.end_time - session_data.start_time))

        participants_tracks[participant_id] = track_changes
    
    return participants_tracks

def _ffmpeg_slice(audio_tracks_path, session_data, participants_tracks_locations):
    participants_tracks_path = {}
    # Create an audio track that is the same size as the main track original and put zero audio outside of the desired track from the participant (so only the participant audio is present in the track, but it is aligned with the main track timeline)
    for participant_id, track_changes in participants_tracks_locations.items():
        participant_track_path = os.path.join(audio_tracks_path, f"track_{participant_id}.wav")
        main_track_path = os.path.join(audio_tracks_path, session_data.main_track_name)
        print(track_changes)
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
            active_expr = " + ".join(
                f"between(t,{start},{end})" for start, end in segments
            )
        else:
            active_expr = "0"

        filter_chain = ",".join([
            "apad=pad_dur=2",
            f"volume=enable='{active_expr}':volume=1",
            f"volume=enable='not({active_expr})':volume=0",
        ])

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i", main_track_path,
            "-af", filter_chain,
            participant_track_path,
        ]
        subprocess.run(ffmpeg_cmd, check=True)

        # participants_tracks_path[participant_id] = participant_track_path
    # return participants_tracks_path    

class Slicer():
    @staticmethod
    def slice_audio_tracks(audio_tracks_path: str, group_slices_by_name: bool = True):
        session_data_dto = _extract_session_dto(audio_tracks_path)
        all_participants_data = _process_participant_data(session_data_dto, group_slices_by_name)
        participants_tracks_locations = _find_participant_tracks(session_data_dto, all_participants_data)
        _ffmpeg_slice(audio_tracks_path, session_data_dto, participants_tracks_locations)

        with open(os.path.join(audio_tracks_path, "slice_metadata.json"), "w") as f:
            json.dump({
                "session_data": session_data_dto.model_dump(),
                "all_participants_data": all_participants_data,
                "participants_tracks_locations": participants_tracks_locations
            }, f, default=str)

    @staticmethod
    def slice_teams_audio_track(audio_tracks_path: str, group_slices_by_name: bool = True) -> Session:
        Slicer.slice_audio_tracks(audio_tracks_path, group_slices_by_name)
        session = Slicer.create_session(audio_tracks_path)
        return session
    
    @staticmethod
    def save_session_data(session: Session, output_path: str):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session.model_dump(), f, default=str, ensure_ascii=False, indent=2)

    @staticmethod
    def create_session(audio_tracks_path: str):
        with open(os.path.join(audio_tracks_path, "slice_metadata.json"), "r") as f:
            metadata = json.load(f)

        session_data_dto = SessionDataDTO(**metadata["session_data"])
        all_participants_data = metadata["all_participants_data"]
        participants_tracks_locations = metadata["participants_tracks_locations"]

        session_tracks = {}
        for participant_id, track_changes in participants_tracks_locations.items():
            participant_name = all_participants_data[participant_id][0]["participant_name"]
            participant_track_path = os.path.join(audio_tracks_path, f"track_{participant_id}.wav")
            session_tracks[participant_id] = ParticipantData(
                participant_id=participant_id,
                participant_name=participant_name,
                track=Track(
                    wav_file_path=participant_track_path
                )
            )
            assert os.path.exists(participant_track_path), f"Expected track file for participant {participant_name} (id: {participant_id}) not found at path: {participant_track_path}. Retry slicing or check for errors in ffmpeg slicing step."
        return Session(
            session_id=session_data_dto.session_id,
            session_start=session_data_dto.start_time,
            session_end=session_data_dto.end_time,
            tracks=session_tracks
        )