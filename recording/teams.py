import argparse
import queue
import re
import time
from urllib.parse import urlparse
from playwright.sync_api import Locator, Page, sync_playwright
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
from models.models import Session
from abc import abstractmethod
from recording.utils import _meeting_origin, _load_text, _write_vad_timeline

_WS_PROC: subprocess.Popen | None = None
_WS_LOCK = threading.Lock()


def _ws_proc_alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def stop_ws_audio_server() -> None:
    global _WS_PROC
    with _WS_LOCK:
        if _ws_proc_alive(_WS_PROC):
            try:
                _WS_PROC.kill()
            except Exception:
                pass
        _WS_PROC = None

_BOT_NAME = "GravAI Bot"
_LAUNCH_BUTTON = re.compile(r"continue on this browser|join on the web|join from this browser", re.IGNORECASE)
_NO_AV_BUTTON = re.compile(r"continue without audio or video", re.IGNORECASE)
_LOBBY_TEXT = re.compile(r"let you in", re.IGNORECASE)
_PREJOIN_TIMEOUT_S = 150
_ERROR_SCREEN_GRACE_S = 20


def _screenshot(page: Page, output_dir: str, name: str) -> None:
    try:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{name}.png")
        page.screenshot(path=path)
        print(f"[teams] screenshot saved to {path}")
    except Exception as exc:
        print(f"[teams] failed to save screenshot '{name}': {exc}")


def _dismiss_overlays(page: Page) -> None:
    """Closes the "Continue without audio or video" dialog, which Teams shows on top of
    the pre-join form (it intercepts clicks on the name input and on "Join now")."""
    try:
        button = page.get_by_role("button", name=_NO_AV_BUTTON).first
        if button.is_visible():
            button.click(timeout=3_000)
            print("[teams] dismissed 'Continue without audio or video' dialog")
    except Exception:
        pass


def _open_meeting_page(page: Page, meeting_url: str) -> None:
    """Opens the meeting link. Teams sometimes takes more than 20 s to deliver the first
    HTML from inside Docker, so wait longer and retry instead of failing on the first try."""
    for attempt in range(1, 4):
        print(f"[teams] opening meeting link (attempt {attempt}/3)...")
        try:
            page.goto(meeting_url, wait_until="domcontentloaded", timeout=60_000)
            return
        except Exception as exc:
            print(f"[teams] opening the meeting link failed (attempt {attempt}/3): {exc.__class__.__name__}")
            if attempt == 3:
                raise RuntimeError(
                    "Could not open the Teams meeting link after 3 attempts (60 s each). "
                    "Check the container's internet connection."
                ) from exc


def _wait_for_prejoin(page: Page, output_dir: str, debug: bool) -> Locator:
    """Waits for the display-name input of the pre-join screen.

    Teams first loads the full web app, which often fails inside Docker with a
    "Retry" screen and then redirects by itself to the light meetings app. The
    whole sequence can take ~40 s, so the retry buttons are only used when the
    error screen stays up for longer than the grace period.
    """
    input_box = page.locator(
        'input[data-tid="prejoin-display-name-input"], '
        'input[id="prejoin-display-name-input"], '
        'input[placeholder*="name" i]'
    ).first
    error_button = page.locator("#error-action")
    clear_cache_button = page.locator("#error-action-clear-cache")

    start = time.time()
    error_since = None
    retries = 0
    next_debug_shot = start
    while time.time() - start < _PREJOIN_TIMEOUT_S:
        try:
            if input_box.is_visible():
                print(f"[teams] pre-join screen loaded after {time.time() - start:.0f}s")
                return input_box

            try:
                page.get_by_role("button", name=_LAUNCH_BUTTON).first.click(timeout=500)
                print("[teams] clicked 'continue on this browser'")
            except Exception:
                pass
            _dismiss_overlays(page)

            if error_button.is_visible():
                error_since = error_since or time.time()
                if time.time() - error_since > _ERROR_SCREEN_GRACE_S and retries < 2:
                    (clear_cache_button if retries == 1 else error_button).click(timeout=5_000)
                    print(f"[teams] error screen persisted, retry #{retries + 1}")
                    retries += 1
                    error_since = None
            else:
                error_since = None
        except Exception:
            # The page navigates several times while loading; locators may fail mid-navigation.
            pass

        if debug and time.time() >= next_debug_shot:
            _screenshot(page, output_dir, f"prejoin_{int(time.time() - start):03d}s")
            next_debug_shot += 15
        page.wait_for_timeout(1_000)

    raise RuntimeError(
        f"Microsoft Teams did not show the pre-join screen within {_PREJOIN_TIMEOUT_S}s. "
        "Check the 'failure.png' screenshot in the session folder."
    )


def _fill_name_and_join(page: Page, input_box: Locator) -> None:
    _dismiss_overlays(page)
    # fill() does not need the input to receive pointer events, so it works even if
    # a dialog is still animating on top of the form.
    input_box.fill(_BOT_NAME)

    join_button = page.get_by_role("button", name=re.compile(r"^join now$", re.IGNORECASE)).first
    for _ in range(3):
        _dismiss_overlays(page)
        try:
            join_button.click(timeout=5_000)
            print("[teams] clicked 'Join now'")
            return
        except Exception as exc:
            print(f"[teams] 'Join now' click failed, retrying: {exc.__class__.__name__}")
    join_button.click(force=True, timeout=5_000)
    print("[teams] clicked 'Join now' (forced)")


def _wait_for_admission_hint(page: Page) -> None:
    try:
        page.get_by_text(_LOBBY_TEXT).first.wait_for(state="visible", timeout=15_000)
        print(f"[teams] waiting in the lobby: admit '{_BOT_NAME}' in the Teams meeting")
    except Exception:
        print("[teams] lobby message not detected; the bot may already be in the meeting")


class MeetingRecorder(BaseModel):
    rtc_intercept_js_path: str
    vad_observer_js_path: str
    audio_worklet_js_path: str

    @abstractmethod
    def record_meeting(self, meeting_url: str, q: Queue, output_dir: str, debug: bool, intercept_js, vad_observer_js, vad_events: list[dict], vad_meta: dict) -> Session:
        pass

    @abstractmethod
    def setup_ws_server(self, meeting_url: str, ws_host: str, ws_port: int, session_id: str) -> tuple[str, str, list[dict], dict]:
        pass

    def record_meeting_with_ws_audio_server(self, meeting_url: str, output_dir: str | None = None, ws_host: str | None = None, ws_port: int | None = None, debug: bool = False):
        settings = Settings()
        debug = debug or settings.RECORDING_DEBUG

        print("Hello from record-meeting!")
        session_id, tracks_output_dir, q, base_output_dir = self.setup(output_dir or settings.SAVE_DIR)
        intercept_js, vad_observer_js, vad_events, vad_meta = self.setup_ws_server(
            meeting_url,
            ws_host or settings.WS_HOST,
            ws_port or settings.WS_PORT,
            session_id,
        )

        print(f"Starting intercept mode session {session_id} -> {tracks_output_dir}")
        p_join_browser = mp.Process(
            target=self.record_meeting,
            args=(meeting_url, q, tracks_output_dir, debug, intercept_js, vad_observer_js, vad_events, vad_meta),
        )
        p_join_browser.start()
        p_join_browser.join()
        print("Finished - Recording")

        try:
            res_type, message = q.get(timeout=5)
        except queue.Empty:
            raise RuntimeError(
                f"Recording process exited (code {p_join_browser.exitcode}) without reporting a result."
            )
        if res_type == "stop":
            return tracks_output_dir
        elif res_type == "exception":
            raise RuntimeError(f"Recording process raised an exception: {message}")
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

        session_id = str(uuid4())
        tracks_output_dir = f"{output_dir}/{session_id}_tracks"

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
        settings = Settings()
        self.audio_worklet_js_path = self.audio_worklet_js_path or settings.AUDIO_WORKLET_JS_PATH
        self.rtc_intercept_js_path = self.rtc_intercept_js_path or settings.RTC_INTERCEPT_JS_PATH
        self.vad_observer_js_path = self.vad_observer_js_path or settings.VAD_OBSERVER_TEAMS_JS_PATH
        self.ws_audio_server_path = self.ws_audio_server_path or settings.WS_AUDIO_SERVER_PATH
        return self

    def setup_ws_server(self, meeting_url: str, ws_host: str, ws_port: int, session_id: str) -> tuple[str, str, list[dict], dict]:
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

        return intercept_js, vad_observer_js, vad_events, vad_meta

    def record_meeting(self, meeting_url: str, q: Queue, output_dir: str, debug: bool, intercept_js, vad_observer_js, vad_events: list[dict], vad_meta: dict) -> Session:
        page = None
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True,
                    ignore_default_args=["--mute-audio"],
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-dev-shm-usage",
                        "--disable-http2",
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

                _open_meeting_page(page, meeting_url)

                input_box = _wait_for_prejoin(page, output_dir, debug)
                _fill_name_and_join(page, input_box)
                _wait_for_admission_hint(page)
                _screenshot(page, output_dir, "after_join")

                try:
                    vad_meta["page_start_ms"] = page.evaluate("() => Date.now()")
                    page.evaluate("() => { if (window.__vadSnapshotRoster) { window.__vadSnapshotRoster(); } }")
                except Exception as exc:
                    print(f"[vad] failed to initialize timeline: {exc}")

                print("Listening and capturing per-track audio...")

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
                rejoin_button_locator = page.get_by_role("button", name=re.compile(r"^rejoin$", re.IGNORECASE))
                rejected_h1_locator = page.locator("h1[id='calling-retry-screen-title']")

                deadline = time.time() + Settings().MAX_RECORDING_SECONDS
                while True:
                    _drain_vad_events()
                    try:
                        rejected_h1_locator.wait_for(state="visible", timeout=200)
                    except Exception:
                        pass
                    else:
                        raise Exception("Rejected from joining the meeting")

                    try:
                        ended_span_locator.or_(removed_h1_locator).or_(rejoin_button_locator).first.wait_for(state="visible", timeout=1000)
                        break
                    except Exception as e:
                        if time.time() >= deadline:
                            print("Meeting end span not detected, closing after timeout.")
                            break

                _drain_vad_events()
                try:
                    vad_meta["page_end_ms"] = page.evaluate("() => Date.now()")
                except Exception as exc:
                    print(f"[vad] failed to capture end time: {exc}")
                try:
                    vad_path = os.path.join(output_dir, "vad_timeline.json")
                    _write_vad_timeline(vad_path, vad_meta, vad_events)
                    print(f"[vad] timeline written to {vad_path}")
                except Exception as exc:
                    print(f"[vad] failed to write timeline: {exc}")

                context.close()
                browser.close()

                q.put(("stop", None))
            except Exception as e:
                print(f"Error in recording process: {e}")
                if page is not None:
                    # Still inside sync_playwright(), so the browser is alive for the screenshot.
                    _screenshot(page, output_dir, "failure")
                q.put(("exception", str(e)))


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Record Meeting Application")
#     parser.add_argument('--meeting_url', type=str, help='URL of the meeting to record')
#     parser.add_argument('--output', type=str, help='Output file path', default="res")
#     parser.add_argument('--ws_host', type=str, help='WS server host')
#     parser.add_argument('--ws_port', type=int, help='WS server port')

#     args = parser.parse_args()
