"""Frame-locked movie WAV capture for fixed-step exports.

The engine movie recorder is started with the ``wav`` format only, so it writes
no TGA frames. DollyNative redirects its GetFramerate accessor to the current
``host_framerate``. The recorder's WAV clock still advances at the requested
movie FPS, which makes the WAV exactly as long as the slow-motion video and
keeps the authored replay window.
"""
from __future__ import annotations

import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

MOVIE_START = re.compile(
    r"Started recording movie:\s+movie/([0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2})/")


class MovieWave:
    """A single ``startmovie <name> wav framerate <fps>`` take."""

    def __init__(self, video: Path, game_executable: Path):
        self.video = Path(video)
        # ...\Deadlock\game\bin\win64\deadlock.exe -> ...\Deadlock\game\citadel
        self.citadel = Path(game_executable).parents[2] / "citadel"
        self.movie_root = self.citadel / "movie"
        self.name = "dolly_audio_" + uuid.uuid4().hex[:10]
        self.folder: Path | None = None
        self.started = False
        self.finished = False
        self.error: str | None = None
        self.movie_engine_seconds: float | None = None

    def start(self, controller, fps: int) -> None:
        if self.started:
            raise RuntimeError("The movie audio take is already recording.")
        if controller is None:
            raise RuntimeError("The game console is not available for movie audio.")
        try:
            pid = controller.game_pid()
        except Exception:
            pid = None
        if pid is not None:
            marker = Path(tempfile.gettempdir()) / f"dolly_movie_audio_{pid}.ready"
            if not marker.is_file():
                raise RuntimeError(
                    "This Dolly native build does not support fixed-step audio. "
                    "Update Dolly or turn off Fixed-step export for audio.")
        # startmovie only records while the in-game console window is closed.
        try:
            controller._request("hideconsole", timeout=4, allow_error=True)
        except Exception:
            pass
        response = controller._request(
            f"startmovie {self.name} wav framerate {int(fps)}", timeout=12,
            allow_error=True)
        match = MOVIE_START.search(response)
        if not match:
            detail = response.strip().splitlines()[-1:] or ["no response"]
            raise RuntimeError("The game did not start the movie audio take: " + detail[0])
        self.folder = self.movie_root / match.group(1)
        self.started = True
        self.movie_engine_seconds = None
        try:
            bridge = controller._native_bridge()
            native = bridge.status() if bridge is not None else {}
            value = native.get("engine_time")
            if value is not None:
                self.movie_engine_seconds = float(value)
        except Exception:
            self.movie_engine_seconds = None
        if self.movie_engine_seconds is None:
            try:
                value = controller.status().get("time")
                if value is not None:
                    self.movie_engine_seconds = float(value)
            except Exception:
                self.movie_engine_seconds = None
        if self.movie_engine_seconds is None:
            try:
                tick_rate = float(controller.replay_tick_rate() or 64.0)
                text = controller._request("demo_goto", timeout=4, allow_error=True)
                tick = re.search(r"Currently playing (\d+) of", text)
                if tick:
                    self.movie_engine_seconds = int(tick.group(1)) / tick_rate
            except Exception:
                pass

    def finish(self, controller, duration: float, work: Path,
               start_engine_seconds: float | None = None,
               speed: float = 1.0) -> Path:
        if not self.started:
            raise RuntimeError("The movie audio take was not started.")
        response = controller._request("endmovie", timeout=45, allow_error=True)
        if "Finishing movie" not in response:
            detail = response.strip().splitlines()[-1:] or ["no response"]
            raise RuntimeError("The game did not finish the movie audio take: " + detail[0])
        self.finished = True
        if self.folder is None:
            raise RuntimeError("The movie audio folder was not reported.")
        source = self.folder / f"{self.name}.wav"
        if not source.is_file() or source.stat().st_size <= 0:
            raise RuntimeError("The movie audio WAV was not written.")
        duration = float(duration)
        if duration <= 0:
            raise RuntimeError("The video did not report a duration for its audio.")
        offset = 0.0
        if start_engine_seconds is not None and self.movie_engine_seconds is not None:
            delta = float(start_engine_seconds) - float(self.movie_engine_seconds)
            if 0.0 <= delta <= 30.0:
                offset = delta / max(0.05, float(speed))
        from .clip_audio import _ffmpeg
        target = Path(work) / "movie_reference.wav"
        command = [str(_ffmpeg()), "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(source), "-ss", f"{offset:.9f}", "-t", f"{duration:.9f}",
                   "-af", "apad", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                   str(target)]
        result = subprocess.run(command, capture_output=True, text=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or not target.is_file() or target.stat().st_size <= 0:
            detail = (result.stderr or "").strip()[-1000:]
            raise RuntimeError("The movie audio WAV could not be converted: " + detail)
        self.cleanup()
        return target

    def cancel(self, controller=None) -> None:
        if self.started and not self.finished and controller is not None:
            try:
                controller._request("endmovie", timeout=15, allow_error=True)
            except Exception:
                pass
        self.cleanup()

    def cleanup(self) -> None:
        if self.folder is None:
            return
        try:
            if self.folder.is_dir() and (not any(self.folder.iterdir()) or
                                         any("dolly_audio_" in child.name.lower()
                                             for child in self.folder.iterdir())):
                shutil.rmtree(self.folder, ignore_errors=True)
        except OSError:
            pass
        self.folder = None
