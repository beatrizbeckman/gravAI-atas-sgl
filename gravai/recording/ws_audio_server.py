import argparse
import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import wave
from array import array
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import websockets


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)


def _float32_to_pcm16(payload: bytes) -> bytes:
    floats = array("f")
    floats.frombytes(payload)
    ints = array("h")
    for f in floats:
        if f > 1.0:
            f = 1.0
        elif f < -1.0:
            f = -1.0
        ints.append(int(f * 32767.0))
    return ints.tobytes()


WAV_SAMPLE_RATE = (
    48000  # the browser worklet streams 48 kHz; the WAV header always says so, whatever the client reports
)


class TrackWriter:
    """Writes one participant track as 16-bit PCM WAV and fixes its playback speed with ffmpeg on close."""

    def __init__(self, output_dir: str, track_id: str, channels: int):
        self.path = os.path.join(output_dir, f"track_{_sanitize_name(track_id)}.wav")
        self._wf = wave.open(self.path, "wb")  # noqa: SIM115  (stays open while the track streams; closed in close())
        self._wf.setnchannels(channels)
        self._wf.setsampwidth(2)
        self._wf.setframerate(WAV_SAMPLE_RATE)

    def write_float32(self, payload: bytes) -> None:
        pcm16 = _float32_to_pcm16(payload)
        self._wf.writeframes(pcm16)

    def close(self) -> None:
        self._wf.close()
        # Apply pitch/tempo correction to fix slow-motion playback.
        fd, tmp_path = tempfile.mkstemp(prefix="track_fix_", suffix=".wav")
        os.close(fd)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    self.path,
                    "-af",
                    "asetrate=96000,aresample=48000,atempo=1",
                    tmp_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            shutil.move(tmp_path, self.path)
        except Exception:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)


def run_server(host: str, port: int, base_output_dir: str) -> None:
    os.makedirs(base_output_dir, exist_ok=True)
    print(f"[ws] base_output_dir={base_output_dir}")
    session_infos: dict[str, dict] = {}

    def _session_output_dir(session_id: str) -> str:
        safe_id = _sanitize_name(session_id)
        suffix = f"{safe_id}_tracks"
        if os.path.basename(base_output_dir) == suffix:
            return base_output_dir
        return os.path.join(base_output_dir, suffix)

    def _get_session(session_id: str | None) -> tuple[str, dict, str, str]:
        sid = session_id or "default"
        info = session_infos.get(sid)
        if not info:
            info = {
                "session_id": sid,
                "session_start": _utc_now(),
                "tracks": {},
            }
            session_infos[sid] = info
        output_dir = _session_output_dir(sid)
        os.makedirs(output_dir, exist_ok=True)
        sidecar_path = os.path.join(output_dir, "session_sidecar.json")
        return sid, info, output_dir, sidecar_path

    def _start_track(session_id: str | None, track_id: str, sample_rate: int, channels: int) -> tuple:
        """Opens the WAV of a track and registers it in the session sidecar."""
        session_id, session_info, output_dir, sidecar_path = _get_session(session_id)
        writer = TrackWriter(output_dir, track_id, channels)
        session_info["tracks"][track_id] = {
            "started_at": _utc_now(),
            "sample_rate": sample_rate,
            "channels": channels,
            "wav_file": os.path.basename(writer.path),
        }
        print(f"[ws] track start {track_id} session_id={session_id} sr={sample_rate} ch={channels}")
        return session_id, session_info, sidecar_path, writer

    async def handler(ws):
        path = getattr(ws, "path", None)
        if path is None and hasattr(ws, "request"):
            path = ws.request.path
        parsed = urlparse(path or "")
        params = parse_qs(parsed.query)
        session_id = params.get("session_id", [None])[0]
        track_id = params.get("track", [None])[0]
        sample_rate = int(params.get("sr", ["48000"])[0])
        channels = int(params.get("ch", ["1"])[0])

        print(f"[ws] client connected {path}")
        writer = None
        session_info = None
        sidecar_path = None
        if track_id:
            session_id, session_info, sidecar_path, writer = _start_track(session_id, track_id, sample_rate, channels)

        try:
            async for message in ws:
                if isinstance(message, str):
                    try:
                        payload = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "start" and not writer:
                        payload_session_id = payload.get("sessionId") or payload.get("session_id")
                        if payload_session_id:
                            session_id = payload_session_id
                        track_id = payload.get("trackId") or payload.get("track_id")
                        if not track_id:
                            continue
                        sample_rate = int(payload.get("sampleRate", sample_rate))
                        channels = int(payload.get("channels", channels))
                        session_id, session_info, sidecar_path, writer = _start_track(
                            session_id, track_id, sample_rate, channels
                        )
                    if payload.get("type") == "stop":
                        break
                    continue

                if writer:
                    writer.write_float32(message)
        finally:
            if writer:
                writer.close()
                if session_info is not None:
                    track = session_info["tracks"].get(track_id, {})
                    track["ended_at"] = _utc_now()
                    session_info["tracks"][track_id] = track
            if session_info is not None and sidecar_path is not None:
                with open(sidecar_path, "w", encoding="utf-8") as f:
                    json.dump(session_info, f, indent=2)

    async def run() -> None:
        async with websockets.serve(handler, host, port, max_size=None):
            stop_event = asyncio.Event()

            def _stop(*_args):
                stop_event.set()

            signal.signal(signal.SIGTERM, _stop)
            signal.signal(signal.SIGINT, _stop)
            await stop_event.wait()

    asyncio.run(run())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WS audio server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output_dir", required=True)
    args = parser.parse_args()
    run_server(args.host, args.port, args.output_dir)
