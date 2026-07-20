
from config.logging_config import get_logger
from models.models import Session
from slicing.slice import Slicer


def slice_track(tracks_output_dir: str, group_slices_by_name: bool = True) -> tuple[str, Session]:
    logger = get_logger("slicing", tracks_output_dir)
    logger.info(f"Slicing started for tracks in {tracks_output_dir}")
    session = Slicer.slice_teams_audio_track(tracks_output_dir, group_slices_by_name)
    metadata_output_path = f"{tracks_output_dir}/session_metadata.json"
    Slicer.save_session_data(session, metadata_output_path)
    logger.info(f"Slicing completed for session {session.session_id}, metadata written to {metadata_output_path}")

    return metadata_output_path, session