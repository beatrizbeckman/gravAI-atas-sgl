import json
from fastapi import FastAPI, HTTPException
from config.settings import Settings
from llm_analyser.analyse_debate import analyze_full_debate
from models.models import Session
from slicing.slice import Slicer
from transcribe.base import transcribe_meeting_tracks
from contextlib import asynccontextmanager

from config.logging_config import get_logger
from recording.service import record_meeting as service_record_meeting
from recording.service import start_ws_server as service_record_start_ws_server
from recording.service import stop_ws_server as service_record_stop_ws_server

from slicing.service import slice_track as service_slice_track

from transcribe.service import transcribe_meeting_tracks as service_transcribe_meeting_tracks

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    service_record_start_ws_server()
    yield
    service_record_stop_ws_server()

app = FastAPI(
    description="record_bot",
    lifespan=lifespan
)

@app.post("/record_meeting")
async def record_meeting(meeting_url: str, slice_tracks: bool = True):
    if "teams.live.com" not in meeting_url and "teams.microsoft.com" not in meeting_url:
        return json.dumps({"error": "Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com'."})

    logger.info(f"Received /record_meeting request for {meeting_url} (slice_tracks={slice_tracks})")
    try:
        tracks_output_dir = service_record_meeting(meeting_url).replace("./", "")
        metadata_output_path, session = None, None
        if slice_tracks:
            metadata_output_path, session = service_slice_track(tracks_output_dir)
    except Exception as e:
        logger.exception(f"/record_meeting failed for {meeting_url}")
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    logger.info(f"/record_meeting completed for {meeting_url} -> {tracks_output_dir}")
    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "session": session}


@app.post("/record_meeting_and_transcribe")
async def record_meeting_and_transcribe(meeting_url: str, group_slices_by_name: bool = True):
    if "teams.live.com" not in meeting_url and "teams.microsoft.com" not in meeting_url:
        return json.dumps({"error": "Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com'."})

    logger.info(f"Received /record_meeting_and_transcribe request for {meeting_url}")
    try:
        tracks_output_dir = service_record_meeting(meeting_url).replace("./", "")
        metadata_output_path, session = service_slice_track(tracks_output_dir, group_slices_by_name)
        transc_session = service_transcribe_meeting_tracks(session)
    except Exception as e:
        logger.exception(f"/record_meeting_and_transcribe failed for {meeting_url}")
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    logger.info(f"/record_meeting_and_transcribe completed for {meeting_url} -> {tracks_output_dir}")
    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "transcribed_slices_session": transc_session}


@app.post("/transcribe")
async def transcribe(tracks_output_dir: str, group_slices_by_name: bool = True):
    logger.info(f"Received /transcribe request for {tracks_output_dir}")
    try:
        metadata_output_path, session = service_slice_track(tracks_output_dir, group_slices_by_name)
        transc_session = service_transcribe_meeting_tracks(session)
    except Exception as e:
        logger.exception(f"/transcribe failed for {tracks_output_dir}")
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    logger.info(f"/transcribe completed for {tracks_output_dir}")
    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "transcribed_slices_session": transc_session}


# def _record_meeting(meeting_url: str) -> str:
    # teams = TeamsMeetingRecorder()
    # tracks_output_dir = teams.record_meeting_with_ws_audio_server(meeting_url)
    # return tracks_output_dir


def _slice_track(tracks_output_dir: str) -> tuple[str, Session]:
    session = Slicer.slice_teams_audio_track(tracks_output_dir)
    metadata_output_path = f"{tracks_output_dir}/session_metadata.json"
    Slicer.save_session_data(session, metadata_output_path)

    return metadata_output_path, session


@app.post("/analyze_transcript")
async def analyze_transcript(tracks_output_dir: str) -> dict:
    try: analysis_result = analyze_full_debate(tracks_output_dir)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return analysis_result

@app.post("/record_transcribe_and_analyze_meeting")
async def record_meeting_and_transcribe(meeting_url: str, group_slices_by_name: bool = True):
    if "teams.live.com" not in meeting_url and "teams.microsoft.com" not in meeting_url:
        return json.dumps({"error": "Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com'."})

    logger.info(f"Received /record_transcribe_and_analyze_meeting request for {meeting_url}")
    try:
        tracks_output_dir = service_record_meeting(meeting_url).replace("./", "")
        _, session = service_slice_track(tracks_output_dir, group_slices_by_name)
        _ = service_transcribe_meeting_tracks(session)
        analysis_result = analyze_full_debate(tracks_output_dir)
    except Exception as e:
        logger.exception(f"/record_transcribe_and_analyze_meeting failed for {meeting_url}")
        raise HTTPException(status_code=500, detail=f"{str(e)}")
    logger.info(f"/record_transcribe_and_analyze_meeting completed for {meeting_url} -> {tracks_output_dir}")
    return analysis_result


@app.post("/health")
async def health_check(): return {"status": "UP"}
