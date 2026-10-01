import json
import os
from fastapi import FastAPI, HTTPException
from config.settings import Settings
from models.models import Session, TranscriptedSession
from recording.teams import TeamsMeetingRecorder, stop_ws_audio_server
from slicing.slice import Slicer
from transcribe.base import transcribe_meeting_tracks
from contextlib import asynccontextmanager
from api.minutes import router as minutes_router
from api.demo import router as demo_router
from jobs.runtime import JobsRuntime

# The WS audio server and the Playwright recorder support a single meeting at a time.
# The lock lives in jobs.executors so the minutes jobs and these endpoints share it.
from jobs.executors import RECORDING_LOCK as _RECORDING_LOCK


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    TeamsMeetingRecorder.launch_ws_server(settings.SAVE_DIR, settings.WS_HOST, settings.WS_PORT, settings.WS_AUDIO_SERVER_PATH)
    # Minutes jobs: SQLite store + one worker thread (see jobs/ and docs/API_MINUTES.md).
    app.state.jobs = JobsRuntime.from_settings()
    app.state.jobs.start()
    yield
    app.state.jobs.stop()
    stop_ws_audio_server()

app = FastAPI(
    description="record_bot",
    lifespan=lifespan
)
app.include_router(minutes_router)
app.include_router(demo_router)

# Endpoints are plain `def` (not `async def`): FastAPI runs them in a worker thread,
# so a recording that blocks for the whole meeting does not freeze the rest of the API.

@app.post("/record_meeting")
def record_meeting(meeting_url: str, slice_tracks: bool = True):
    _validate_meeting_url(meeting_url)

    try:
        tracks_output_dir = _record_meeting(meeting_url)
        metadata_output_path, session = None, None
        if slice_tracks:
            metadata_output_path, session = _slice_track(tracks_output_dir)
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "session": session}


@app.post("/transcribe")
def transcribe(tracks_output_dir: str):
    _validate_tracks_dir(tracks_output_dir)

    try:
        metadata_output_path, session = _slice_track(tracks_output_dir)
        transc_session = _transcribe_session(tracks_output_dir, session)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "transcribed_slices_session": transc_session}


@app.post("/record_meeting_and_transcribe")
def record_meeting_and_transcribe(meeting_url: str):
    _validate_meeting_url(meeting_url)

    try:
        tracks_output_dir = _record_meeting(meeting_url)
        metadata_output_path, session = _slice_track(tracks_output_dir)
        transc_session = _transcribe_session(tracks_output_dir, session)
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return {"recording_path": tracks_output_dir, "session_metadata_path": metadata_output_path, "transcribed_slices_session": transc_session}


@app.post("/analyze_transcript")
def analyze_transcript(tracks_output_dir: str) -> dict:
    _validate_tracks_dir(tracks_output_dir)

    # Imported lazily so the API starts even when the Groq variables are not configured.
    from llm_analyser.analyse_debate import analyze_full_debate

    try:
        analysis_result = analyze_full_debate(tracks_output_dir)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"{str(e)}")

    return analysis_result


def _validate_meeting_url(meeting_url: str) -> None:
    if "teams.live.com" not in meeting_url and "teams.microsoft.com" not in meeting_url:
        raise HTTPException(
            status_code=400,
            detail="Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com' or 'teams.microsoft.com'.",
        )


def _validate_tracks_dir(tracks_output_dir: str) -> None:
    if not os.path.isdir(tracks_output_dir):
        raise HTTPException(status_code=404, detail=f"Recording folder not found: {tracks_output_dir}")


def _record_meeting(meeting_url: str) -> str:
    if not _RECORDING_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A meeting is already being recorded. Try again when it finishes.")
    try:
        teams = TeamsMeetingRecorder()
        return teams.record_meeting_with_ws_audio_server(meeting_url)
    finally:
        _RECORDING_LOCK.release()


def _slice_track(tracks_output_dir: str) -> tuple[str, Session]:
    session = Slicer.slice_teams_audio_track(tracks_output_dir)
    metadata_output_path = f"{tracks_output_dir}/session_metadata.json"
    Slicer.save_session_data(session, metadata_output_path)

    return metadata_output_path, session


def _transcribe_session(tracks_output_dir: str, session: Session) -> TranscriptedSession:
    transc_session = transcribe_meeting_tracks(session)
    with open(f"{tracks_output_dir}/session_transcription.json", "w", encoding="utf-8") as f:
        json.dump(transc_session.model_dump(), f, default=str, ensure_ascii=False, indent=2)
    return transc_session
