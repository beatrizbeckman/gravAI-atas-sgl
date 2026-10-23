import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from gravai.api.cors import add_cors
from gravai.api.demo import router as demo_router
from gravai.api.minutes import router as minutes_router
from gravai.config import Settings
from gravai.jobs.runtime import JobsRuntime
from gravai.recording import pipeline
from gravai.recording.teams import TeamsMeetingRecorder, stop_ws_audio_server
from gravai.recording.utils import is_teams_meeting_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    TeamsMeetingRecorder.launch_ws_server(
        settings.SAVE_DIR, settings.WS_HOST, settings.WS_PORT, settings.WS_AUDIO_SERVER_PATH
    )
    # Minutes jobs: SQLite store + one worker thread (see jobs/ and docs/API_MINUTES.md).
    app.state.jobs = JobsRuntime.from_settings()
    app.state.jobs.start()
    yield
    app.state.jobs.stop()
    stop_ws_audio_server()


app = FastAPI(description="record_bot", lifespan=lifespan)
add_cors(app, Settings().CORS_ORIGINS)
app.include_router(minutes_router)
app.include_router(demo_router)

# Endpoints are plain `def` (not `async def`): FastAPI runs them in a worker thread,
# so a recording that blocks for the whole meeting does not freeze the rest of the API.


@app.post("/record_meeting")
def record_meeting(meeting_url: str, slice_tracks: bool = True) -> dict:
    _validate_meeting_url(meeting_url)
    try:
        tracks_dir = _record(meeting_url)
        metadata_path, session = pipeline.slice_tracks(tracks_dir) if slice_tracks else (None, None)
    except HTTPException:
        raise
    except Exception as exc:
        raise _internal_error(exc) from exc
    return {"recording_path": tracks_dir, "session_metadata_path": metadata_path, "session": session}


@app.post("/transcribe")
def transcribe(tracks_output_dir: str) -> dict:
    _validate_tracks_dir(tracks_output_dir)
    try:
        metadata_path, transcribed = pipeline.slice_and_transcribe(tracks_output_dir)
    except Exception as exc:
        raise _internal_error(exc) from exc
    return {
        "recording_path": tracks_output_dir,
        "session_metadata_path": metadata_path,
        "transcribed_slices_session": transcribed,
    }


@app.post("/record_meeting_and_transcribe")
def record_meeting_and_transcribe(meeting_url: str) -> dict:
    _validate_meeting_url(meeting_url)
    try:
        tracks_dir = _record(meeting_url)
        metadata_path, transcribed = pipeline.slice_and_transcribe(tracks_dir)
    except HTTPException:
        raise
    except Exception as exc:
        raise _internal_error(exc) from exc
    return {
        "recording_path": tracks_dir,
        "session_metadata_path": metadata_path,
        "transcribed_slices_session": transcribed,
    }


@app.post("/analyze_transcript")
def analyze_transcript(tracks_output_dir: str) -> dict:
    _validate_tracks_dir(tracks_output_dir)

    # Imported lazily so the API starts even when the Groq variables are not configured.
    from gravai.legacy.llm_analyser.analyse_debate import analyze_full_debate

    try:
        return analyze_full_debate(tracks_output_dir)
    except Exception as exc:
        raise _internal_error(exc) from exc


# ---------------------------------------------------------------- helpers


def _validate_meeting_url(meeting_url: str) -> None:
    if not is_teams_meeting_url(meeting_url):
        raise HTTPException(
            status_code=400,
            detail="Only Teams meetings are supported at the moment. Make sure the url contains 'teams.live.com' or 'teams.microsoft.com'.",
        )


def _validate_tracks_dir(tracks_output_dir: str) -> None:
    if not os.path.isdir(tracks_output_dir):
        raise HTTPException(status_code=404, detail=f"Recording folder not found: {tracks_output_dir}")


def _record(meeting_url: str) -> str:
    try:
        return pipeline.record_meeting(meeting_url)
    except pipeline.RecordingBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _internal_error(exc: Exception) -> HTTPException:
    print(exc)
    return HTTPException(status_code=500, detail=str(exc))
