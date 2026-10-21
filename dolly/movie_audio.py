"""Frame-locked movie WAV capture for fixed-step exports.

The engine movie recorder is started with the ``wav`` format only, so it writes
no TGA frames. DollyNative redirects its GetFramerate accessor to the current
``host_framerate``. The recorder's WAV clock still advances at the requested
movie FPS, which makes the WAV exactly as long as the slow-motion video and
keeps the authored replay window.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import tempfile
from typing import Callable
import uuid

from .file_ops import _plain_path

MOVIE_START = re.compile(
    r"Started recording movie:\s+movie/([0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2})/")


@dataclass(frozen=True)
class MovieOutputContext:
    root: Path
    verify_owner: Callable[[object], None] = field(repr=False, compare=False)


class MovieWave:
    """A single ``startmovie <name> wav framerate <fps>`` take."""

    def __init__(self, video: Path, game_executable: Path, *, output_context: MovieOutputContext | None = None):
        self.video = Path(video)
        # ...\Deadlock\game\bin\win64\deadlock.exe -> ...\Deadlock\game\citadel
        self.citadel = Path(game_executable).parents[2] / "citadel"
        self._output_context = output_context
        self.movie_root = output_context.root if output_context is not None else self.citadel / "movie"
        self._root = self.movie_root
        self._controller = None
        self._capture_folder = None
        self._capture_name = None
        self._directory_ids = {}
        self.name = "dolly_audio_" + uuid.uuid4().hex[:10]
        self.folder: Path | None = None
        self.started = False
        self.finished = False
        self.error: str | None = None
        self.movie_engine_seconds: float | None = None

    def _verify_output(self, controller=None) -> None:
        if self._controller is not None and controller is not None and controller is not self._controller:
            raise RuntimeError("The movie audio controller changed; its files were kept.")
        if self._output_context is not None:
            self._output_context.verify_owner(controller if controller is not None else self._controller)
        if self.movie_root != self._root or not self.movie_root.is_absolute():
            raise RuntimeError("The movie audio output root changed; its files were kept.")
        paths = [self.movie_root]
        if self.folder is not None:
            if self.folder != self._capture_folder or self.name != self._capture_name:
                raise RuntimeError("The movie audio capture identity changed; its files were kept.")
            paths.extend((self.folder, self.folder / (self.name + ".wav")))
        try:
            for path in paths:
                for part in (path, *path.parents):
                    try:
                        if not _plain_path(part):
                            raise RuntimeError("Linked movie audio paths were left untouched.")
                    except FileNotFoundError:
                        continue
            for directory in (self.movie_root, self.folder):
                if directory is None or not directory.exists():
                    continue
                if not directory.is_dir():
                    raise RuntimeError("The movie audio directory changed; its files were kept.")
                info = directory.stat()
                identity = (info.st_dev, info.st_ino)
                previous = self._directory_ids.setdefault(directory, identity)
                if previous != identity:
                    raise RuntimeError("The movie audio directory changed; its files were kept.")
        except OSError as exc:
            raise RuntimeError("Could not verify movie audio paths; their files were kept.") from exc

    def start(self, controller, fps: int) -> None:
        if self.started:
            raise RuntimeError("The movie audio take is already recording.")
        if controller is None:
            raise RuntimeError("The game console is not available for movie audio.")
        if not re.fullmatch(r'dolly_audio_[0-9a-f]{10}', self.name):
            raise RuntimeError("The movie audio capture name is invalid.")
        self._verify_output(controller)
        self._controller = controller
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
        self._verify_output(controller)
        response = controller._request(
            f"startmovie {self.name} wav framerate {int(fps)}", timeout=12,
            allow_error=True)
        match = MOVIE_START.search(response)
        if not match:
            detail = response.strip().splitlines()[-1:] or ["no response"]
            raise RuntimeError("The game did not start the movie audio take: " + detail[0])
        self._verify_output(controller)
        self.folder = self.movie_root / match.group(1)
        self._capture_folder, self._capture_name = self.folder, self.name
        self._verify_output(controller)
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
        self._verify_output(controller)
        response = controller._request("endmovie", timeout=45, allow_error=True)
        if "Finishing movie" not in response:
            detail = response.strip().splitlines()[-1:] or ["no response"]
            raise RuntimeError("The game did not finish the movie audio take: " + detail[0])
        self.finished = True
        self._verify_output(controller)
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
        self._verify_output(controller)
        if self.started and not self.finished and controller is not None:
            try:
                controller._request("endmovie", timeout=15, allow_error=True)
            except Exception:
                pass
        self.cleanup()

    def cleanup(self) -> None:
        if self.folder is None:
            return
        self._verify_output()
        try:
            # This timestamp directory may contain a second recording or an
            # unknown file. Only this take's exact WAV belongs to us.
            source = self.folder / (self.name + ".wav")
            if source.is_file():
                source.unlink()
            self.folder.rmdir()  # Remove only an empty directory; keep siblings.
        except OSError:
            pass
        if self._output_context is not None:
            try:
                self.movie_root.rmdir()  # Only our empty per-session MOD root.
            except OSError:
                pass
        self.folder = None
