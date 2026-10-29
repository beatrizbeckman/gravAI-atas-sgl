import json
import os

import requests

from gravai.config import Settings
from gravai.models import ParticipantDataTransc, Session, TranscriptedSession, Transcription


def transcribe_meeting_tracks(
    session: Session, whisper_server_host: str | None = None, whisper_server_port: int | None = None
):
    settings = Settings()
    whisper_host = whisper_server_host or settings.WHISPER_HOST
    whisper_port = whisper_server_port or settings.WHISPER_PORT
    tracks = {}
    for participant_id, participant_data in session.tracks.items():
        wav_file_path = participant_data.track.wav_file_path
        transcription = transcribe(wav_file_path, whisper_host, whisper_port)
        transcription_text = transcription.get("text", "")
        transcription_segments = transcription.get("segments", [])
        base_path = os.path.splitext(wav_file_path)[0]
        transcription_text_output_path = base_path + "_transcription_text.txt"
        transcription_segments_output_path = base_path + "_transcription_segments.json"
        with open(transcription_text_output_path, "w", encoding="utf-8") as f:
            f.write(transcription_text)
        with open(transcription_segments_output_path, "w", encoding="utf-8") as f:
            json.dump(transcription_segments, f, ensure_ascii=False, indent=2)

        print(
            f"Transcription for participant {participant_data.participant_name} (id: {participant_id}):\n{transcription}\n"
        )
        tracks[participant_id] = ParticipantDataTransc(
            participant_id=participant_id,
            participant_name=participant_data.participant_name,
            track=participant_data.track,
            transcription=Transcription(
                transcription_text_file_path=transcription_text_output_path,
                transcription_segments_file_path=transcription_segments_output_path,
            ),
        )

    return TranscriptedSession(
        session_id=session.session_id,
        session_start=session.session_start,
        session_end=session.session_end,
        tracks=tracks,
    )


def transcribe(audio_file: str, whisper_server_host: str, whisper_server_port: int) -> dict:
    settings = Settings()
    with open(audio_file, "rb") as audio:
        response = requests.post(
            f"http://{whisper_server_host}:{whisper_server_port}/inference",
            files={"file": (os.path.basename(audio_file), audio, "audio/wav")},
            data={
                "temperature": "0.0",
                "response_format": "verbose_json",
                # Each 30 s window is transcribed on its own. With the previous window's text as
                # context, whisper invents a subtitle credit on the silence at the start of a track
                # and then repeats it in every window, wiping out the real speech that follows.
                "max_context": "0",
                # The server's own --language comes from the compose file and is blank when the
                # container was created without --env-file; sending it here makes it not matter.
                "language": settings.WHISPER_LANGUAGE,
                # Beam search instead of greedy: fewer swapped words ("texto" for "testes").
                "beam_size": str(settings.WHISPER_BEAM_SIZE),
            },
            # Long meetings on CPU can take a while; fail instead of hanging forever.
            timeout=3_600,
        )
    if response.status_code != 200:
        raise Exception(f"Error from whisper server: {response.status_code} {response.text}")

    # whisper.cpp usually returns the transcription under the "text" key when using verbose_json
    return response.json()
