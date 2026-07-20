from config.settings import Settings
from config.logging_config import get_logger
from recording.providers.teams.provider import TeamsMeetingRecorder, stop_ws_audio_server

logger = get_logger("recording.service")


def start_ws_server(
	output_dir: str | None = None,
	ws_host: str | None = None,
	ws_port: int | None = None,
	ws_server_path: str | None = None,
) -> None:
	settings = Settings() # type: ignore
	logger.info("Starting WS audio server")
	TeamsMeetingRecorder.launch_ws_server(
		output_dir or settings.SAVE_DIR,
		ws_host or settings.WS_HOST,
		ws_port or settings.WS_PORT,
		ws_server_path or settings.WS_AUDIO_SERVER_PATH,
	)


def stop_ws_server() -> None:
	logger.info("Stopping WS audio server")
	stop_ws_audio_server()


def record_meeting(
	meeting_url: str,
	output_dir: str | None = None,
	ws_host: str | None = None,
	ws_port: int | None = None,
	debug: bool = False,
) -> str:
	recorder = TeamsMeetingRecorder()
	return recorder.record_meeting_with_ws_audio_server(
		meeting_url,
		output_dir=output_dir,
		ws_host=ws_host,
		ws_port=ws_port,
		debug=debug,
	)
