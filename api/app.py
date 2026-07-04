import json
from fastapi import FastAPI, HTTPException
from config.settings import Settings
from llm_analyser.analyse_debate import analyze_full_debate
from models.models import Session
from recording.teams import TeamsMeetingRecorder, stop_ws_audio_server
from slicing.slice import Slicer
from transcribe.base import transcribe_meeting_tracks
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    TeamsMeetingRecorder.launch_ws_server(settings.SAVE_DIR, settings.WS_HOST, settings.WS_PORT, settings.WS_AUDIO_SERVER_PATH)
    yield
    stop_ws_audio_server()

app = FastAPI(
    description="record_bot",
    lifespan=lifespan
)

@app.post("/record_meeting")
async def record_meeting(meeting_url: str, slice_tracks: bool = True):
    if "teams.live.com" not in meeting_url and "teams.microsoft.com" not in meeting_url:
        return json.dumps({"error": "Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com'."})

    try:
        tracks_output_dir = _record_meeting(meeting_url)
        metadata_output_path, session = None, None
        if slice_tracks:
            metadata_output_path, session = _slice_track(tracks_output_dir)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "session": session}


@app.post("/transcribe")
async def transcribe(tracks_output_dir: str):
    try:
        metadata_output_path, session = _slice_track(tracks_output_dir)
        transc_session = transcribe_meeting_tracks(session)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "transcribed_slices_session": transc_session}


def _record_meeting(meeting_url: str) -> str:
    teams = TeamsMeetingRecorder()
    tracks_output_dir = teams.record_meeting_with_ws_audio_server(meeting_url)
    return tracks_output_dir


def _slice_track(tracks_output_dir: str) -> tuple[str, Session]:
    session = Slicer.slice_teams_audio_track(tracks_output_dir)
    metadata_output_path = f"{tracks_output_dir}/session_metadata.json"
    Slicer.save_session_data(session, metadata_output_path)

    return metadata_output_path, session


@app.post("/record_meeting_and_transcribe")
async def record_meeting_and_transcribe(meeting_url: str):
    if "teams.live.com" not in meeting_url and "teams.microsoft.com" not in meeting_url:
        return json.dumps({"error": "Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com'."})

    try:
        tracks_output_dir = _record_meeting(meeting_url)
        metadata_output_path, session = _slice_track(tracks_output_dir)

        transc_session = transcribe(session)
        print("Transcrição dir: ", transc_session)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "transcribed_slices_session": transc_session}


@app.post("/analyze_transcript")
async def analyze_transcript(tracks_output_dir: str) -> dict:
    try: analysis_result = analyze_full_debate(tracks_output_dir)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return analysis_result
