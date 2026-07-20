from enum import Enum
from datetime import datetime
from pydantic import BaseModel

class Singleton(object):
    _instances = {}
    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__new__(cls, *args, **kwargs)
        return cls._instances[cls]

class ActionType(Enum):
    START = 0
    END = 1

class TrackInfoDTO(BaseModel):
    # action: ActionType
    participant_name: str
    element_id: str
    timestamp: int
    class_count: int
    # segments: list[AudioSegmentTime]

class SessionDataDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    main_track_name: str
    session_id: str
    events: list[TrackInfoDTO]

class Track(BaseModel):
    # start_time: int
    # end_time: int
    wav_file_path: str

class ParticipantData(BaseModel):
    participant_id: str
    participant_name: str
    track: Track

class Transcription(BaseModel):
    transcription_text_file_path: str
    transcription_segments_file_path: str

class ParticipantDataTransc(BaseModel):
    participant_id: str
    participant_name: str
    track: Track
    transcription: Transcription

class Session(BaseModel):
    session_id: str
    session_start: datetime
    session_end: datetime
    tracks: dict[str, ParticipantData] # Map participant_id to ParticipantData

class TranscriptedSession(BaseModel):
    session_id: str
    session_start: datetime
    session_end: datetime
    tracks: dict[str, ParticipantDataTransc] # Map participant_id to ParticipantData
