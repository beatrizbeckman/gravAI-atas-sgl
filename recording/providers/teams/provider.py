import argparse
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
import multiprocessing as mp
from multiprocessing import Process, Queue
import os
import subprocess
import sys
import json
import threading
from uuid import uuid4
from pydantic import BaseModel, model_validator

from config.settings import Settings
from config.logging_config import get_logger
from models.models import Session
from abc import abstractmethod
from recording.utils import _meeting_origin, _load_text, _write_vad_timeline
from datetime import datetime

_WS_PROC: subprocess.Popen | None = None
_WS_LOCK = threading.Lock()


def _ws_proc_alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def stop_ws_audio_server() -> None:
    global _WS_PROC
    with _WS_LOCK:
        if _ws_proc_alive(_WS_PROC):
            try:
                _WS_PROC.kill() # type: ignore
            except Exception:
                pass
        _WS_PROC = None

class MeetingRecorder(BaseModel):
    rtc_intercept_js_path: str | None
    vad_observer_js_path: str | None
    audio_worklet_js_path: str | None

    @abstractmethod
    def record_meeting(self, meeting_url: str, q: Queue, output_dir: str, debug: bool, intercept_js, vad_observer_js, vad_events: list[dict], vad_meta: dict):
        pass

    @abstractmethod
    def setup_ws_server(self, meeting_url: str, ws_host: str, ws_port: int, session_id: str) -> tuple[str, str, list[dict], dict, str]:
        pass

    def record_meeting_with_ws_audio_server(self, meeting_url: str, output_dir: str | None = None, ws_host: str | None = None, ws_port: int | None = None, debug: bool = False):
        settings = Settings() # type: ignore

        session_id, tracks_output_dir, q, base_output_dir = self.setup(output_dir or settings.SAVE_DIR)
        logger = get_logger("recording.teams", tracks_output_dir)
        logger.info(f"Setup complete for session {session_id} (meeting_url={meeting_url}, output_dir={tracks_output_dir})")

        # The intercept_js and vad_obeserver_js are modified with the ws_url and injected in the browser
        # they are responsible for recording and sending the audio packages to the WS server
        intercept_js, vad_observer_js, vad_events, vad_meta, ws_url = self.setup_ws_server(
            meeting_url,
            ws_host or settings.WS_HOST,
            ws_port or settings.WS_PORT,
            session_id,
        )

        logger.info(f"Starting intercept mode session {session_id} -> {tracks_output_dir}")
        p_join_browser = mp.Process(
            target=self.record_meeting,
            args=(meeting_url, q, tracks_output_dir, debug, intercept_js, vad_observer_js, vad_events, vad_meta),
        )

        p_join_browser.start()

        try:
            p_join_browser.join()
        except KeyboardInterrupt:
            logger.warning("Keyboard interrupt received, signaling recording process to stop...")
            q.put(("keyboard_interrupt", None))
            p_join_browser.join()

        res = q.get_nowait()
        res_type, message = res
        if res_type == "stop":
            logger.info(f"Recording finished successfully for session {session_id}")
            return tracks_output_dir
        elif res_type == "exception":
            logger.error(f"Recording process raised an exception for session {session_id}: {message}")
            raise RuntimeError(f"Recording process raised an exception: {message}")
        logger.error(f"Recording process for session {session_id} did not report a start/stop signal")
        raise RuntimeError("Did not receive expected start/stop signals from recording process.")


    def setup(self, output_dir: str):
        try:
            mp.set_start_method('spawn', force=True)
        except RuntimeError:
            pass

        q = mp.Queue()

        if not output_dir:
            output_dir = "/tmp"
        os.makedirs(output_dir, exist_ok=True)

        session_prefix = datetime.today().strftime("%Y_%m_%d")
        session_id = f"{session_prefix}_{str(uuid4())}"

        tracks_output_dir = f"{output_dir}/{session_id}_tracks"

        get_logger("recording.teams", tracks_output_dir).info(
            f"Setup started at {datetime.now().isoformat()} for session {session_id}"
        )

        return session_id, tracks_output_dir, q, output_dir
        
    @staticmethod
    def launch_ws_server(output_dir, ws_host, ws_port, ws_server_path):
        os.makedirs(output_dir, exist_ok=True)
        global _WS_PROC
        with _WS_LOCK:
            if not _ws_proc_alive(_WS_PROC):
                _WS_PROC = subprocess.Popen([
                    sys.executable,
                    ws_server_path,
                    "--host", ws_host,
                    "--port", str(ws_port),
                    "--output_dir", output_dir,
                ])

class TeamsMeetingRecorder(MeetingRecorder):
    rtc_intercept_js_path: str | None = None
    vad_observer_js_path: str | None = None
    audio_worklet_js_path: str | None = None
    ws_audio_server_path: str | None = None

    @model_validator(mode="after")
    def assemble_es_hosts(self) -> "TeamsMeetingRecorder":
        """Constructs the ES_HOSTS URL after model validation."""
        settings = Settings() # type: ignore
        self.audio_worklet_js_path = self.audio_worklet_js_path or settings.AUDIO_WORKLET_JS_PATH
        self.rtc_intercept_js_path = self.rtc_intercept_js_path or settings.RTC_INTERCEPT_JS_PATH
        self.vad_observer_js_path = self.vad_observer_js_path or settings.VAD_OBSERVER_TEAMS_JS_PATH
        self.ws_audio_server_path = self.ws_audio_server_path or settings.WS_AUDIO_SERVER_PATH
        return self

    def setup_ws_server(self, meeting_url: str, ws_host: str, ws_port: int, session_id: str) -> tuple[str, str, list[dict], dict, str]:
        worklet_path = self.audio_worklet_js_path
        intercept_path = self.rtc_intercept_js_path
        vad_observer_path = self.vad_observer_js_path
        ws_server_path = self.ws_audio_server_path

        assert worklet_path and intercept_path and vad_observer_path and ws_server_path, "Expected worklet, intercept, vad observer, and ws server paths to be set"

        # Expect WS Server to be launched

        worklet_js = _load_text(worklet_path)
        intercept_js = _load_text(intercept_path)
        vad_observer_js = _load_text(vad_observer_path)
        ws_url = f"ws://{ws_host}:{ws_port}?session_id={session_id}"
        intercept_js = intercept_js.replace("{{WS_URL}}", ws_url).replace("{{WORKLET_CODE}}", json.dumps(worklet_js))
        vad_events: list[dict] = []
        vad_meta = {
            "session_id": session_id,
            "meeting_url": meeting_url,
            "page_start_ms": None,
            "page_end_ms": None,
        }

        return intercept_js, vad_observer_js, vad_events, vad_meta, ws_url    

    def record_meeting(self, meeting_url: str, q: Queue, output_dir: str, debug: bool, intercept_js, vad_observer_js, vad_events: list[dict], vad_meta: dict):
        logger = get_logger("recording.teams", output_dir)
        try:
            with sync_playwright() as p:
                logger.info("Launching headless Chromium browser")
                browser = p.chromium.launch(
                    headless=True,
                    ignore_default_args=["--mute-audio"],
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--enable-logging",
                        "--v=1",
                        "--vmodule=*webrtc*=3,*libjingle*=3",
                    ],
                )
                context = browser.new_context(bypass_csp=True, ignore_https_errors=True)
                context.add_init_script(intercept_js)
                context.add_init_script(vad_observer_js)
                context.grant_permissions([], origin=_meeting_origin(meeting_url))

                page = context.new_page()
                page.set_default_timeout(20_000)

                logger.info(f"Navigating to meeting URL: {meeting_url}")
                page.goto(meeting_url, wait_until="domcontentloaded")
                logger.info("Prejoin page DOM content loaded")

                try:
                    page.locator("prejoin-join-button").first.click(timeout=9000)
                    logger.info("Prejoin page stage: clicked prejoin-join-button")
                except Exception:
                    logger.info("Prejoin page stage: prejoin-join-button not present, skipping")
                if debug:
                    page.screenshot(path="prejoin.png")
                try:
                    page.locator(".btn.primary").first.click(timeout=3000)
                    logger.info("Prejoin page stage: clicked primary button")
                except Exception:
                    logger.info("Prejoin page stage: primary button not present, skipping")
                try:
                    if debug:
                        page.screenshot(path="prejoin2.png")
                    page.get_by_role("button", name="Continue without audio or video").first.click(timeout=8000)
                    logger.info("Prejoin page stage: clicked 'Continue without audio or video'")
                except Exception:
                    logger.info("Prejoin page stage: 'Continue without audio or video' not present, skipping")

                if debug:
                    page.screenshot(path="prejoin3.png")

                try:
                    input_box = page.locator('input[data-tid="prejoin-display-name-input"]')
                    input_box.wait_for(timeout=30000)
                except Exception:
                    input_box = page.locator("input").first

                input_box.click(timeout=10_000)
                input_box.fill("GravAI Bot")
                logger.info("Prejoin page stage: display name filled in")

                try:
                    page.get_by_role("button", name="Join now").first.click(timeout=5000)
                    logger.info("Clicked 'Join now' button, waiting to enter the meeting room")
                except Exception:
                    logger.warning("Failed to click 'Join now' button, attempting keyboard fallback to submit join")
                    for _ in range(4):
                        page.keyboard.press("Tab")
                    page.keyboard.press("Enter")

                if debug:
                    page.screenshot(path="last_wait.png")

                try:
                    vad_meta["page_start_ms"] = page.evaluate("() => Date.now()")
                    page.evaluate("() => { if (window.__vadSnapshotRoster) { window.__vadSnapshotRoster(); } }")
                except Exception as exc:
                    logger.warning(f"[vad] failed to initialize timeline: {exc}")

                logger.info("Waiting to be admitted into the meeting room / listening for audio activity...")

                def _drain_vad_events() -> None:
                    try:
                        new_events = page.evaluate(
                            """
                            () => {
                                const events = Array.isArray(window.__vadEvents) ? window.__vadEvents : [];
                                window.__vadEvents = [];
                                return events;
                            }
                            """
                        )
                    except Exception:
                        return
                    if new_events:
                        vad_events.extend(new_events)

                ended_span_locator = page.locator("span:has-text('Did you leave by mistake?')")
                removed_h1_locator = page.locator("h1:has-text(\"You've been removed from this meeting\")")
                rejected_h1_locator = page.locator("h1[id='calling-retry-screen-title']")

                deadline = time.time() + 7_200

                last_vad_event_time_update = time.time()
                last_vad_event_count = 0
                joined_meeting_logged = False
                while True:
                    _drain_vad_events()
                    try:
                        rejected_h1_locator.wait_for(state="visible", timeout=200)
                    except Exception:
                        pass
                    else:
                        logger.error("Entry to the meeting was rejected/denied by the host")
                        raise Exception("Rejected from joining the meeting")

                    try:
                        if len(vad_events) != last_vad_event_count:
                            if not joined_meeting_logged:
                                logger.info("Audio activity detected: successfully joined the meeting and started recording")
                                joined_meeting_logged = True
                            last_vad_event_time_update = time.time()
                            last_vad_event_count = len(vad_events)
                        # Checks for inactivity in VAD events to determine if the meeting has likely ended,
                        # as a fallback in case the end-of-meeting indicators are not detected
                        elif time.time() - last_vad_event_time_update > 4200:
                            logger.info("No audio activity detected for a prolonged period, assuming meeting ended")
                            break

                        ended_span_locator.or_(removed_h1_locator).wait_for(state="visible", timeout=1000)
                        logger.info("Meeting end detected (left the meeting or was removed)")
                        break
                    except Exception as e:
                        if time.time() >= deadline:
                            logger.warning("Meeting end span not detected, closing after timeout.")
                            break

                _drain_vad_events()
                try:
                    vad_meta["page_end_ms"] = page.evaluate("() => Date.now()")
                except Exception as exc:
                    logger.warning(f"[vad] failed to capture end time: {exc}")
                try:
                    vad_path = os.path.join(output_dir, "vad_timeline.json")
                    _write_vad_timeline(vad_path, vad_meta, vad_events)
                    logger.info(f"[vad] timeline written to {vad_path}")
                except Exception as exc:
                    logger.warning(f"[vad] failed to write timeline: {exc}")

                context.close()
                browser.close()
                logger.info("Browser closed, recording session finished")

                q.put(("stop", None))
        except Exception as e:
            logger.exception(f"Error in recording process: {e}")
            q.put(("exception", str(e)))


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Record Meeting Application")
#     parser.add_argument('--meeting_url', type=str, help='URL of the meeting to record')
#     parser.add_argument('--output', type=str, help='Output file path', default="res")
#     parser.add_argument('--ws_host', type=str, help='WS server host')
#     parser.add_argument('--ws_port', type=int, help='WS server port')

#     args = parser.parse_args()
