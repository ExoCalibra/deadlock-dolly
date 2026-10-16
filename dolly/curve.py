"""Editable camera graphs using the same sampler as shot playback.

Position, rotation and aspect share one horizontal timeline. Drag previews
stay local until release and change only the selected value at its existing
camera timestamp. Graph edits never retime the replay.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import math
import tkinter as tk
from tkinter import ttk

from .path import ASPECT_MIN, ASPECT_MAX, CURVE_CHANNELS, Project, channel_value
from . import ui_theme


_TOKEN = ui_theme.TOKENS
_FONT = ui_theme.FONT_SIZES
BACKGROUND = _TOKEN["field"]
GRID = _TOKEN["edge"]
TEXT = _TOKEN["strong"]
MUTED = _TOKEN["muted"]
ACCENT = _TOKEN["accent"]
ROTATION_ACCENT = _TOKEN["warn"]
CHANNEL_LABELS = {"pitch": "Pitch", "yaw": "Yaw", "roll": "Roll"}
# Position edits replace existing camera coordinates; they are not curve_* overrides.
POSITION_CHANNELS = ("x", "y", "z")
POSITION_LIMIT = 1e8  # Existing native path visualization validity limit.


def clamp_aspect(value: float) -> float:
    """Constrain an authored aspect to Dolly's supported framing range."""
    if not math.isfinite(value):
        raise ValueError("Aspect ratio must be finite")
    return max(ASPECT_MIN, min(ASPECT_MAX, value))


@dataclass(frozen=True)
class PlotBounds:
    left: float
    top: float
    right: float
    bottom: float
    start: float
    end: float
    low: float
    high: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def point(self, time: float, value: float) -> tuple[float, float]:
        span = self.end - self.start if self.end > self.start else 1.0
        return (self.left + (time - self.start) / span * (self.right - self.left),
                self.bottom - (value - self.low) / (self.high - self.low)
                * (self.bottom - self.top))

    def time_at(self, x: float) -> float:
        width = self.right - self.left if self.right > self.left else 1.0
        return self.start + (x - self.left) / width * (self.end - self.start)

    def value_at(self, y: float) -> float:
        return self.low + (self.bottom - y) / (self.bottom - self.top) * (self.high - self.low)

    def aspect_at(self, y: float) -> float:
        return clamp_aspect(self.value_at(y))


@dataclass
class TimelineView:
    """Shared horizontal zoom for the framing graphs (video-timeline style).

    ``end <= start`` means the full shot is shown; every other value is an
    explicit window that both graphs render so their time axes stay aligned.
    """

    start: float = 0.0
    end: float = 0.0

    def window(self, duration: float) -> tuple[float, float]:
        full = max(float(duration), 0.001)
        if self.end <= self.start:
            return 0.0, full
        start = min(max(0.0, self.start), full)
        end = min(max(start + 0.001, self.end), full)
        return start, end

    def zoom(self, factor: float, anchor: float, duration: float) -> None:
        full = max(float(duration), 0.001)
        start, end = self.window(full)
        span = end - start
        new_span = min(max(span * factor, full / 500.0), full)
        anchor = min(max(anchor, start), end)
        ratio = (anchor - start) / span if span > 0 else 0.0
        start = min(max(0.0, anchor - ratio * new_span), full - new_span)
        self.start, self.end = start, start + new_span

    def pan(self, delta: float, duration: float) -> None:
        full = max(float(duration), 0.001)
        start, end = self.window(full)
        span = end - start
        start = min(max(0.0, start + delta), full - span)
        self.start, self.end = start, start + span

    def reset(self) -> None:
        self.start = self.end = 0.0


def plot_bounds(width: float, height: float, project: Project,
                view: TimelineView | None = None,
                limits: tuple[float, float] | None = None,
                duration: float | None = None) -> PlotBounds:
    """Bounds for the visible window; the full shot stays the default view."""
    total = float(duration if duration is not None else
                  (project.duration if project.duration > 0 else 1.0))
    start, end = (view or TimelineView()).window(total)
    low, high = limits if limits else (ASPECT_MIN, ASPECT_MAX)
    return PlotBounds(48.0, 19.0, max(70.0, width - 18.0), max(46.0, height - 28.0),
                      start, end, low, high)


def sample_channel(project: Project, name: str, start: float, end: float,
                   samples: int = 160) -> list[tuple[float, float]]:
    """Sample one evaluated channel, preserving step jumps and authored keys."""
    start, end = float(start), float(end)
    if end <= start:
        end = start + 1.0
    if not project.keyframes:
        value = float(project.standard_aspect) if name == "aspect_ratio" else 0.0
        return [(start, value), (end, value)]
    samples = max(2, min(256, samples))
    interpolation = project.lens_interpolation if name == "aspect_ratio" else project.interpolation
    times = {start + (end - start) * index / (samples - 1) for index in range(samples)}
    for key in project.keyframes:
        key_time = float(key.time)
        if start <= key_time <= end:
            times.add(key_time)
            if interpolation == "step" and key_time > start:
                times.add(math.nextafter(key_time, -math.inf))
    channel = project.camera_channel_samples(name)
    return [(time, channel.evaluate(time)) for time in sorted(times)]


def sample_curve(project: Project, duration: float, samples: int = 160,
                 start: float = 0.0) -> list[tuple[float, float]]:
    """Sample the real aspect evaluator for the graph."""
    return sample_channel(project, "aspect_ratio", float(start), float(duration), samples)


def hit_key(points: list[tuple[float, float]], x: float, y: float, radius: float = 12.0) -> int | None:
    """Find the nearest key within a useful pointer target, including overlapped keys."""
    if not points:
        return None
    distances = [(px - x) ** 2 + (py - y) ** 2 for px, py in points]
    index = min(range(len(points)), key=distances.__getitem__)
    return index if distances[index] <= radius * radius else None


class _GraphViewMixin:
    """Wheel zoom, right-drag pan, and double-click reset shared by the graphs."""

    view: TimelineView
    on_view = None

    def _install_view_bindings(self):
        self._pan_x = None
        self.canvas.bind("<MouseWheel>", self._view_wheel)
        self.canvas.bind("<ButtonPress-3>", self._view_pan_press)
        self.canvas.bind("<B3-Motion>", self._view_pan_motion)
        self.canvas.bind("<ButtonRelease-3>", self._view_pan_release)
        self.canvas.bind("<Double-Button-1>", self._view_reset)

    def _view_duration(self) -> float:
        raise NotImplementedError

    def _view_wheel(self, event):
        if not getattr(self, "_enabled", False) or self._bounds is None:
            return
        bounds = self._bounds
        x = min(max(event.x, bounds.left), bounds.right)
        factor = 0.85 if event.delta > 0 else 1.0 / 0.85
        self.view.zoom(factor, bounds.time_at(x), self._view_duration())
        self._after_view_change()
        return "break"

    def _view_pan_press(self, event):
        if not getattr(self, "_enabled", False) or self._bounds is None:
            return
        self._pan_x = event.x

    def _view_pan_motion(self, event):
        if self._pan_x is None or self._bounds is None:
            return
        bounds = self._bounds
        span = bounds.end - bounds.start
        width = max(1.0, bounds.right - bounds.left)
        self.view.pan(-(event.x - self._pan_x) / width * span, self._view_duration())
        self._pan_x = event.x
        self._after_view_change()

    def _view_pan_release(self, _event):
        self._pan_x = None

    def _view_reset(self, _event=None):
        if not getattr(self, "_enabled", False):
            return
        self.view.reset()
        self._after_view_change()

    def _after_view_change(self):
        if callable(getattr(self, "on_view", None)):
            self.on_view()
        else:
            self._schedule_redraw()

    def _schedule_redraw(self, _event=None):
        """Coalesce redraw bursts (wheel/pan/resize) into one idle redraw."""
        if getattr(self, "_redraw_scheduled", False):
            return
        self._redraw_scheduled = True
        self.after_idle(self._run_scheduled_redraw)

    def _run_scheduled_redraw(self):
        self._redraw_scheduled = False
        self._redraw()


class AspectCurve(_GraphViewMixin, ttk.Frame):
    """Compact graph. Callbacks receive selection or one committed framing edit.

    ``on_change(index, time, aspect)`` owns validation and updating the project;
    ``on_select(index)`` can synchronize the camera list and inspector. This
    widget never mutates the caller's Project. Arrow keys edit the selected key
    by 0.01, or by 0.1 with Shift. Escape abandons an unfinished drag.
    """

    def __init__(self, parent, on_change, on_select, *, height: int = 145, view=None,
                 on_view=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_change = on_change
        self.on_select = on_select
        self.on_view = on_view
        self.view = view if view is not None else TimelineView()
        self.project = Project()
        self.selected_index = None
        self.current_time = 0.0
        self._enabled = True
        self._drag_index = None
        self._drag_value = None
        self._drag_bounds = None
        self._preview = None
        self._bounds = None
        self._points = []
        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0,
                                borderwidth=0, height=height, width=300, takefocus=True)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.hint = ttk.Label(self, text="Drag a key to set framing · ↑/↓ fine tune · wheel zoom · right-drag pan",
                              foreground=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["small"]))
        self.hint.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas.bind("<Configure>", self._schedule_redraw)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<KeyPress-Up>", self._key)
        self.canvas.bind("<KeyPress-Down>", self._key)
        self.canvas.bind("<KeyPress-Escape>", self._cancel)
        self._install_view_bindings()

    def _view_duration(self) -> float:
        return self.project.duration if self.project.duration > 0 else 1.0

    def set_project(self, project: Project, selected_index=None, current_time: float = 0.0):
        if project is not self.project or (self._drag_index is not None
                                          and self._drag_index >= len(project.keyframes)):
            self._clear_drag()
        self.project = project
        self.selected_index = (selected_index if isinstance(selected_index, int)
                               and 0 <= selected_index < len(project.keyframes) else None)
        self.current_time = max(0.0, float(current_time))
        self._redraw()

    def set_current_time(self, current_time: float):
        """Move just the playhead during playback without resampling the graph."""
        self.current_time = max(0.0, float(current_time))
        self._draw_playhead()

    def set_enabled(self, enabled: bool):
        """Prevent framing edits while the app is busy or a shot is playing."""
        self._enabled = bool(enabled)
        if not self._enabled and self._drag_index is not None:
            self._cancel()
        self.hint.configure(text=("Drag a key to set framing · ↑/↓ fine tune · wheel zoom · right-drag pan"
                                  if self._enabled else "Pause playback to edit framing"))

    def _redraw(self, _event=None):
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 90 or height < 55:
            return
        project = self._preview or self.project
        bounds = self._drag_bounds or plot_bounds(width, height, project, self.view)
        self._bounds = bounds
        for index in range(4):
            value = bounds.low + (bounds.high - bounds.low) * index / 3
            _, y = bounds.point(bounds.start, value)
            canvas.create_line(bounds.left, y, bounds.right, y, fill=GRID)
            canvas.create_text(bounds.left - 9, y, text=f"{value:.2f}", anchor="e",
                               fill=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        for index in range(5):
            timestamp = bounds.start + (bounds.end - bounds.start) * index / 4
            x, _ = bounds.point(timestamp, bounds.low)
            canvas.create_line(x, bounds.top, x, bounds.bottom, fill=GRID)
            canvas.create_text(x, bounds.bottom + 14, text=f"{timestamp:g}s", fill=MUTED,
                               font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        canvas.create_text(bounds.left, 7, text="ASPECT RATIO", anchor="w", fill=MUTED,
                           font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        _, standard_y = bounds.point(bounds.start, project.standard_aspect)
        canvas.create_line(bounds.left, standard_y, bounds.right, standard_y,
                           fill=MUTED, dash=(3, 5))
        canvas.create_text(bounds.right, 7, text=f"Standard {project.standard_aspect:.3f}",
                           anchor="e", fill=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        samples = sample_curve(project, bounds.end, max(40, int(width / 4)), start=bounds.start)
        coordinates = [coordinate for timestamp, aspect in samples
                       for coordinate in bounds.point(timestamp, aspect)]
        canvas.create_line(*coordinates, fill=ACCENT, width=2)
        self._points = [bounds.point(key.time, key.aspect_ratio) for key in project.keyframes]
        for index, (x, y) in enumerate(self._points):
            selected = index == self.selected_index
            radius = 6 if selected else 4
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                               fill=TEXT if selected else ACCENT, outline=BACKGROUND, width=2)
        self._draw_playhead()

    def _draw_playhead(self):
        self.canvas.delete("playhead")
        if self._bounds is None:
            return
        bounds = self._bounds
        if not bounds.start <= self.current_time <= bounds.end:
            return
        x, _ = bounds.point(self.current_time, bounds.low)
        self.canvas.create_line(x, bounds.top, x, bounds.bottom, fill=MUTED,
                                width=1, dash=(2, 3), tags="playhead")

    def _press(self, event):
        if not self._enabled:
            return
        self.canvas.focus_set()
        index = hit_key(self._points, event.x, event.y)
        if index is None:
            return
        self.selected_index = index
        self._drag_index = index
        self._drag_value = None
        self._drag_bounds = self._bounds
        self.on_select(index)
        self._redraw()

    def _motion(self, event):
        if self._drag_index is None or self._drag_bounds is None:
            return
        self._drag_value = round(self._drag_bounds.aspect_at(event.y), 4)
        self._preview = copy.copy(self.project)
        self._preview.keyframes = list(self.project.keyframes)
        self._preview.keyframes[self._drag_index] = replace(
            self.project.keyframes[self._drag_index], aspect_ratio=self._drag_value)
        self._redraw()

    def _release(self, _event):
        index, value = self._drag_index, self._drag_value
        self._clear_drag()
        try:
            if index is not None and value is not None and index < len(self.project.keyframes):
                key = self.project.keyframes[index]
                if abs(value - key.aspect_ratio) > 1e-6:
                    self.on_change(index, key.time, value)
        finally:
            self._redraw()

    def _clear_drag(self):
        self._drag_index = None
        self._drag_value = None
        self._drag_bounds = None
        self._preview = None

    def _cancel(self, _event=None):
        self._clear_drag()
        self._redraw()
        return "break"

    def _key(self, event):
        if (not self._enabled or self._drag_index is not None or self.selected_index is None
                or not 0 <= self.selected_index < len(self.project.keyframes)):
            return "break"
        key = self.project.keyframes[self.selected_index]
        increment = 0.1 if event.state & 0x0001 else 0.01
        if event.keysym == "Down":
            increment = -increment
        value = clamp_aspect(round(key.aspect_ratio + increment, 4))
        if value != key.aspect_ratio:
            self.on_change(self.selected_index, key.time, value)
        self._redraw()
        return "break"


def rotation_bounds(width: float, height: float, project: Project, channel: str,
                    view: TimelineView | None = None, samples: int = 120) -> PlotBounds:
    """Degree bounds for the visible rotation window with a usable minimum span."""
    total = project.duration if project.duration > 0 else 1.0
    start, end = (view or TimelineView()).window(total)
    values = [value for _, value in sample_channel(project, channel, start, end, samples)]
    low, high = (min(values), max(values)) if values else (0.0, 0.0)
    if high - low < 20.0:
        middle = (low + high) / 2.0
        low, high = middle - 10.0, middle + 10.0
    else:
        pad = (high - low) * 0.15
        low, high = low - pad, high + pad
    return PlotBounds(48.0, 19.0, max(70.0, width - 18.0), max(46.0, height - 28.0),
                      start, end, low, high)


class RotationCurve(_GraphViewMixin, ttk.Frame):
    """Editable pitch/yaw/roll curve overriding camera key angles.

    ``on_change(index, channel, value)`` commits one override; the dashed line
    is the authored camera motion and the solid line is the effective curve.
    """

    def __init__(self, parent, on_change, on_select, on_reset, *, height: int = 130,
                 view=None, on_view=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_change = on_change
        self.on_select = on_select
        self.on_reset = on_reset
        self.on_view = on_view
        self.view = view if view is not None else TimelineView()
        self.project = Project()
        self.selected_index = None
        self.current_time = 0.0
        self.channel = CURVE_CHANNELS[0]
        self._enabled = True
        self._drag_index = None
        self._drag_value = None
        self._drag_bounds = None
        self._preview = None
        self._bounds = None
        self._points = []
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="ROTATION", foreground=MUTED,
                  font=(ui_theme.FONT_FAMILY, _FONT["tiny"])).grid(row=0, column=0, sticky="w")
        self.channel_box = ttk.Combobox(header, values=[CHANNEL_LABELS[name] for name in CURVE_CHANNELS],
                                        state="readonly", width=7)
        self.channel_box.current(CURVE_CHANNELS.index(self.channel))
        self.channel_box.grid(row=0, column=1, sticky="e")
        self.channel_box.bind("<<ComboboxSelected>>", self._channel_changed)
        self.reset_button = ttk.Button(header, text="Reset", width=6, command=self._reset)
        self.reset_button.grid(row=0, column=2, sticky="e", padx=(4, 0))
        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0,
                                borderwidth=0, height=height, width=300, takefocus=True)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.hint = ttk.Label(self, text="Drag to shape rotation · wheel zoom · right-drag pan",
                              foreground=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["small"]))
        self.hint.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.canvas.bind("<Configure>", self._schedule_redraw)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<KeyPress-Up>", self._key)
        self.canvas.bind("<KeyPress-Down>", self._key)
        self.canvas.bind("<KeyPress-Escape>", self._cancel)
        self._install_view_bindings()

    def _view_duration(self) -> float:
        return self.project.duration if self.project.duration > 0 else 1.0

    def set_project(self, project: Project, selected_index=None, current_time: float = 0.0):
        if project is not self.project or (self._drag_index is not None
                                          and self._drag_index >= len(project.keyframes)):
            self._clear_drag()
        self.project = project
        self.selected_index = (selected_index if isinstance(selected_index, int)
                               and 0 <= selected_index < len(project.keyframes) else None)
        self.current_time = max(0.0, float(current_time))
        self._redraw()

    def set_current_time(self, current_time: float):
        """Move just the playhead during playback without resampling the graph."""
        self.current_time = max(0.0, float(current_time))
        self._draw_playhead()

    def set_enabled(self, enabled: bool):
        """Prevent curve edits while the app is busy or a shot is playing."""
        self._enabled = bool(enabled)
        if not self._enabled and self._drag_index is not None:
            self._cancel()
        self.channel_box.configure(state="readonly" if self._enabled else "disabled")
        self.reset_button.configure(state="normal" if self._enabled else "disabled")
        self.hint.configure(text=("Drag to shape rotation · wheel zoom · right-drag pan"
                                  if self._enabled else "Pause playback to edit rotation"))

    def _channel_changed(self, _event=None):
        index = self.channel_box.current()
        channel = CURVE_CHANNELS[index] if 0 <= index < len(CURVE_CHANNELS) else CURVE_CHANNELS[0]
        if channel != self.channel:
            self._clear_drag()
            self.channel = channel
        self._redraw()

    def _reset(self):
        if self._enabled:
            self.on_reset(self.channel)

    def _redraw(self, _event=None):
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 90 or height < 45:
            return
        project = self._preview or self.project
        bounds = self._drag_bounds or rotation_bounds(width, height, project, self.channel, self.view)
        self._bounds = bounds
        for index in range(4):
            value = bounds.low + (bounds.high - bounds.low) * index / 3
            _, y = bounds.point(bounds.start, value)
            canvas.create_line(bounds.left, y, bounds.right, y, fill=GRID)
            canvas.create_text(bounds.left - 9, y, text=f"{value:.0f}°", anchor="e",
                               fill=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        for index in range(5):
            timestamp = bounds.start + (bounds.end - bounds.start) * index / 4
            x, _ = bounds.point(timestamp, bounds.low)
            canvas.create_line(x, bounds.top, x, bounds.bottom, fill=GRID)
            canvas.create_text(x, bounds.bottom + 13, text=f"{timestamp:g}s", fill=MUTED,
                               font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        canvas.create_text(bounds.left, 7, text=f"ROTATION · {CHANNEL_LABELS[self.channel].upper()}",
                           anchor="w", fill=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        base_project = copy.copy(project)
        base_project.keyframes = [replace(key, **{"curve_" + self.channel: None})
                                  for key in project.keyframes]
        base = sample_channel(base_project, self.channel, bounds.start, bounds.end,
                              max(40, int(width / 4)))
        base_coordinates = [coordinate for timestamp, value in base
                            for coordinate in bounds.point(timestamp, value)]
        if len(base_coordinates) >= 4:
            canvas.create_line(*base_coordinates, fill=MUTED, width=1, dash=(3, 3))
        samples = sample_channel(project, self.channel, bounds.start, bounds.end,
                                 max(40, int(width / 4)))
        coordinates = [coordinate for timestamp, value in samples
                       for coordinate in bounds.point(timestamp, value)]
        if len(coordinates) >= 4:
            canvas.create_line(*coordinates, fill=ROTATION_ACCENT, width=2)
        self._points = [bounds.point(key.time, channel_value(key, self.channel))
                        for key in project.keyframes]
        for index, (x, y) in enumerate(self._points):
            overridden = getattr(project.keyframes[index], "curve_" + self.channel) is not None
            selected = index == self.selected_index
            radius = 6 if selected else 4
            if selected:
                fill = TEXT
            elif overridden:
                fill = ROTATION_ACCENT
            else:
                fill = BACKGROUND
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill,
                               outline=ROTATION_ACCENT, width=2)
        self._draw_playhead()

    def _draw_playhead(self):
        self.canvas.delete("playhead")
        if self._bounds is None:
            return
        bounds = self._bounds
        if not bounds.start <= self.current_time <= bounds.end:
            return
        x, _ = bounds.point(self.current_time, bounds.low)
        self.canvas.create_line(x, bounds.top, x, bounds.bottom, fill=MUTED,
                                width=1, dash=(2, 3), tags="playhead")

    def _press(self, event):
        if not self._enabled:
            return
        self.canvas.focus_set()
        index = hit_key(self._points, event.x, event.y)
        if index is None:
            return
        self.selected_index = index
        self._drag_index = index
        self._drag_value = None
        self._drag_bounds = self._bounds
        self.on_select(index)
        self._redraw()

    def _motion(self, event):
        if self._drag_index is None or self._drag_bounds is None:
            return
        self._drag_value = round(self._drag_bounds.value_at(event.y), 2)
        self._preview = copy.copy(self.project)
        self._preview.keyframes = list(self.project.keyframes)
        field = "curve_" + self.channel
        self._preview.keyframes[self._drag_index] = replace(
            self.project.keyframes[self._drag_index], **{field: self._drag_value})
        self._redraw()

    def _release(self, _event):
        index, value = self._drag_index, self._drag_value
        self._clear_drag()
        try:
            if index is not None and value is not None and index < len(self.project.keyframes):
                key = self.project.keyframes[index]
                if abs(value - channel_value(key, self.channel)) > 1e-6:
                    self.on_change(index, self.channel, value)
        finally:
            self._redraw()

    def _clear_drag(self):
        self._drag_index = None
        self._drag_value = None
        self._drag_bounds = None
        self._preview = None

    def _cancel(self, _event=None):
        self._clear_drag()
        self._redraw()
        return "break"

    def _key(self, event):
        if (not self._enabled or self._drag_index is not None or self.selected_index is None
                or not 0 <= self.selected_index < len(self.project.keyframes)):
            return "break"
        key = self.project.keyframes[self.selected_index]
        increment = 10.0 if event.state & 0x0001 else 1.0
        if event.keysym == "Down":
            increment = -increment
        value = round(channel_value(key, self.channel) + increment, 2)
        if abs(value - channel_value(key, self.channel)) > 1e-6:
            self.on_change(self.selected_index, self.channel, value)
        self._redraw()
        return "break"


@dataclass(frozen=True)
class PositionBounds(PlotBounds):
    """World-unit mapping that also handles very large finite saved coordinates."""

    def point(self, time: float, value: float) -> tuple[float, float]:
        scale = max(abs(self.low), abs(self.high), 1.0)
        fraction = (value / scale - self.low / scale) / (self.high / scale - self.low / scale)
        span = self.end - self.start if self.end > self.start else 1.0
        return (self.left + (time - self.start) / span * (self.right - self.left),
                self.bottom - fraction * (self.bottom - self.top))

    def value_at(self, y: float) -> float:
        scale = max(abs(self.low), abs(self.high), 1.0)
        fraction = (self.bottom - y) / (self.bottom - self.top)
        return scale * (self.low / scale + fraction * (self.high / scale - self.low / scale))


def position_bounds(width: float, height: float, project: Project, channel: str,
                    view: TimelineView | None = None, samples: int = 120) -> PositionBounds:
    """Fit the evaluated XYZ curve, including overshoot, in world units."""
    if channel not in POSITION_CHANNELS:
        raise ValueError("Choose X, Y or Z for the position graph")
    total = project.duration if project.duration > 0 else 1.0
    start, end = (view or TimelineView()).window(total)
    values = [value for _, value in sample_channel(project, channel, start, end, samples)
              if math.isfinite(value)]
    values.extend(float(getattr(key, channel)) for key in project.keyframes
                  if start <= key.time <= end)
    low, high = (min(values), max(values)) if values else (0.0, 0.0)
    scale = max(abs(low), abs(high), 1.0)
    middle = (low / scale + high / scale) / 2
    span = max(high / scale - low / scale, 20.0 / scale, 1e-12)
    limit = float.fromhex("0x1.fffffffffffffp+1023") / scale
    low = max(-limit, middle - span * .65) * scale
    high = min(limit, middle + span * .65) * scale
    return PositionBounds(62.0, 19.0, max(84.0, width - 18.0), max(46.0, height - 28.0),
                          start, end, low, high)


class PositionCurve(_GraphViewMixin, ttk.Frame):
    """XYZ values at fixed camera times, using the saved path's evaluator.

    A drag is a private graph preview. Only release or an explicit numeric
    commit calls ``on_change(index, axis, value)``; opening/selecting does not
    seek or move the game camera. Attached keys remain readable but not editable.
    """

    def __init__(self, parent, on_change, on_select, *, height=130, view=None,
                 on_view=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_change, self.on_select, self.on_view = on_change, on_select, on_view
        self.view = view if view is not None else TimelineView()
        self.project = Project()
        self.channel = "x"
        self.selected_index = None
        self.current_time = 0.0
        self._enabled = True
        self._bounds, self._points = None, []
        self._editing_value = False
        self._value_origin = None
        self._clear_drag()
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="POSITION", foreground=MUTED,
                  font=(ui_theme.FONT_FAMILY, _FONT["tiny"])).grid(row=0, column=0, sticky="w")
        self.channel_box = ttk.Combobox(header, values=("X", "Y", "Z"), state="readonly", width=3)
        self.channel_box.current(0)
        self.channel_box.grid(row=0, column=1, sticky="e", padx=(5, 8))
        self.channel_box.bind("<<ComboboxSelected>>", self._channel_changed)
        self.value_text = tk.StringVar(self, "")
        self.value_entry = ttk.Entry(header, textvariable=self.value_text, width=11)
        self.value_entry.grid(row=0, column=2, sticky="e")
        self.value_entry.bind("<FocusIn>", self._begin_value)
        self.value_entry.bind("<Return>", self._apply_value)
        self.value_entry.bind("<Escape>", self._cancel_value)
        self.value_entry.bind("<FocusOut>", self._cancel_value)
        ttk.Label(header, text="units", foreground=MUTED,
                  font=(ui_theme.FONT_FAMILY, _FONT["small"])).grid(row=0, column=3, padx=(4, 0))
        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0,
                                borderwidth=0, height=height, width=300, takefocus=True)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.hint = ttk.Label(self, foreground=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["small"]))
        self.hint.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.canvas.bind("<Configure>", self._schedule_redraw)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<KeyPress-Up>", self._key)
        self.canvas.bind("<KeyPress-Down>", self._key)
        self.canvas.bind("<KeyPress-Escape>", self._cancel)
        self.canvas.bind("<FocusOut>", self._cancel)
        self.bind("<Unmap>", self._cancel)
        self._install_view_bindings()
        self._sync_value()

    def _view_duration(self):
        return self.project.duration if self.project.duration > 0 else 1.0

    def _editable(self, index=None):
        index = self.selected_index if index is None else index
        return (self._enabled and isinstance(index, int) and not isinstance(index, bool)
                and 0 <= index < len(self.project.keyframes)
                and self.project.keyframes[index].source == "free")

    def _sync_value(self):
        selected = (isinstance(self.selected_index, int) and not isinstance(self.selected_index, bool)
                    and 0 <= self.selected_index < len(self.project.keyframes))
        if self._editing_value and not self._value_current():
            self._editing_value, self._value_origin = False, None
        if not self._editing_value:
            self.value_text.set(repr(getattr(self.project.keyframes[self.selected_index], self.channel))
                                if selected else "")
        state = "normal" if self._editable() else "disabled"
        self.value_entry.configure(state=state)
        self.channel_box.configure(state="readonly" if self._enabled else "disabled")
        if not self._enabled:
            message = "Pause playback to edit position"
        elif selected and not self._editable():
            message = "Authored free-camera position; attached keys follow their target"
        elif not selected:
            message = "Select a free-camera key to edit position in world units"
        elif self._editing_value:
            message = "Enter applies position; Escape or leaving the field cancels"
        else:
            message = "Drag value \u00b7 Up/Down 1 unit \u00b7 Shift 10 \u00b7 wheel zoom"
        self.hint.configure(text=message)

    def set_project(self, project: Project, selected_index=None, current_time=0.0):
        if self._drag_index is not None and (
                project is not self._drag_project or project != self._drag_snapshot
                or selected_index != self._drag_index):
            self._clear_drag()
        self.project = project
        self.selected_index = (selected_index if isinstance(selected_index, int)
                               and not isinstance(selected_index, bool)
                               and 0 <= selected_index < len(project.keyframes) else None)
        self.current_time = max(0.0, float(current_time))
        self._sync_value()
        self._redraw()

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not self._enabled:
            self._clear_drag()
        self._sync_value()
        self._redraw()

    def set_current_time(self, current_time):
        self.current_time = max(0.0, float(current_time))
        self._draw_playhead()

    def _after_view_change(self):
        self._clear_drag()
        super()._after_view_change()

    def _channel_changed(self, _event=None):
        self._clear_drag()
        self._cancel_value()
        index = self.channel_box.current()
        self.channel = POSITION_CHANNELS[index] if 0 <= index < 3 else "x"
        self._sync_value()
        self._redraw()

    def _begin_value(self, _event=None):
        if self._editable() and not self._editing_value:
            self._editing_value = True
            self._value_origin = (self.project, copy.deepcopy(self.project),
                                  self.selected_index, self.channel)
            self._sync_value()

    def _value_current(self):
        if not self._editing_value or self._value_origin is None:
            return False
        project, snapshot, index, channel = self._value_origin
        return (self._editable() and self.project is project and self.project == snapshot
                and self.selected_index == index and self.channel == channel)

    def _cancel_value(self, _event=None):
        self._editing_value, self._value_origin = False, None
        self._sync_value()
        return "break"

    def _apply_value(self, _event=None):
        if not self._value_current():
            self._cancel_value()
            return "break"
        try:
            value = float(self.value_text.get())
        except (ValueError, OverflowError):
            value = math.nan
        if not math.isfinite(value) or abs(value) > POSITION_LIMIT:
            self.hint.configure(text="Enter a position between -100,000,000 and 100,000,000 world units")
            return "break"
        self._clear_drag()
        self._editing_value, self._value_origin = False, None
        index = self.selected_index
        if value != getattr(self.project.keyframes[index], self.channel):
            self.on_change(index, self.channel, value)
        self._sync_value()
        self._redraw()
        return "break"

    def _redraw(self, _event=None):
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 100 or height < 55:
            return
        project = self._preview or self.project
        bounds = self._drag_bounds or position_bounds(width, height, project, self.channel, self.view)
        self._bounds = bounds
        for index in range(4):
            y = bounds.bottom - (bounds.bottom - bounds.top) * index / 3
            value = bounds.value_at(y)
            canvas.create_line(bounds.left, y, bounds.right, y, fill=GRID)
            canvas.create_text(bounds.left - 8, y, text=f"{value:.4g}", anchor="e",
                               fill=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        for index in range(5):
            timestamp = bounds.start + (bounds.end - bounds.start) * index / 4
            x, _ = bounds.point(timestamp, bounds.low)
            canvas.create_line(x, bounds.top, x, bounds.bottom, fill=GRID)
            canvas.create_text(x, bounds.bottom + 13, text=f"{timestamp:g}s", fill=MUTED,
                               font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        canvas.create_text(bounds.left, 7, text=f"{self.channel.upper()} \u00b7 WORLD UNITS", anchor="w",
                           fill=MUTED, font=(ui_theme.FONT_FAMILY, _FONT["tiny"]))
        samples = sample_channel(project, self.channel, bounds.start, bounds.end,
                                 max(40, int(width / 4)))
        coordinates = [coordinate for time, value in samples if math.isfinite(value)
                       for coordinate in bounds.point(time, value)]
        if len(coordinates) >= 4:
            canvas.create_line(*coordinates, fill=ACCENT, width=2)
        self._points = [bounds.point(key.time, getattr(key, self.channel)) for key in project.keyframes]
        for index, (x, y) in enumerate(self._points):
            if not bounds.left <= x <= bounds.right:
                continue
            radius = 6 if index == self.selected_index else 4
            fill = TEXT if index == self.selected_index else ACCENT
            if project.keyframes[index].source != "free":
                fill = BACKGROUND
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                               fill=fill, outline=ACCENT, width=2)
        self._draw_playhead()

    def _draw_playhead(self):
        self.canvas.delete("playhead")
        if self._bounds is not None and self._bounds.start <= self.current_time <= self._bounds.end:
            x, _ = self._bounds.point(self.current_time, self._bounds.low)
            self.canvas.create_line(x, self._bounds.top, x, self._bounds.bottom, fill=MUTED,
                                    width=1, dash=(2, 3), tags="playhead")

    def _press(self, event):
        if not self._enabled:
            return
        self.canvas.focus_set()
        self._cancel_value()
        self._clear_drag()
        index = hit_key(self._points, event.x, event.y)
        if index is None:
            return
        self.selected_index = index
        self.on_select(index)
        self._sync_value()
        if self._editable(index):
            self._drag_index, self._drag_bounds = index, self._bounds
            self._drag_project = self.project
            self._drag_snapshot = copy.deepcopy(self.project)
            self._drag_channel = self.channel
            self._drag_press_y = event.y
            self._drag_origin_value = getattr(self.project.keyframes[index], self.channel)
        self._redraw()

    def _gesture_current(self):
        return (self._drag_index is not None and self._editable(self._drag_index)
                and self.project is self._drag_project and self.project == self._drag_snapshot
                and self.channel == self._drag_channel and self.selected_index == self._drag_index)

    def _motion(self, event):
        if not self._gesture_current() or self._drag_bounds is None:
            self._cancel()
            return
        delta = self._drag_bounds.value_at(event.y) - self._drag_bounds.value_at(self._drag_press_y)
        value = self._drag_origin_value + delta
        if not math.isfinite(value) or abs(value) > POSITION_LIMIT:
            self._cancel()
            return
        self._drag_value = value
        self._preview = copy.copy(self.project)
        self._preview.keyframes = list(self.project.keyframes)
        self._preview.keyframes[self._drag_index] = replace(
            self.project.keyframes[self._drag_index], **{self.channel: self._drag_value})
        self._redraw()

    def _release(self, _event=None):
        valid = self._gesture_current()
        index, value, channel = self._drag_index, self._drag_value, self._drag_channel
        self._clear_drag()
        try:
            if valid and value is not None and value != getattr(self.project.keyframes[index], channel):
                self.on_change(index, channel, value)
        finally:
            self._sync_value()
            self._redraw()

    def _clear_drag(self):
        self._drag_index = self._drag_value = self._drag_bounds = self._preview = None
        self._drag_project = self._drag_snapshot = self._drag_channel = None
        self._drag_press_y = self._drag_origin_value = None

    def _cancel(self, _event=None):
        self._clear_drag()
        self._cancel_value()
        if hasattr(self, "canvas"):
            self._redraw()
        return "break"

    def _key(self, event):
        if not self._editable() or self._drag_index is not None:
            return "break"
        increment = 10.0 if event.state & 1 else 1.0
        if event.keysym == "Down":
            increment = -increment
        value = getattr(self.project.keyframes[self.selected_index], self.channel) + increment
        if (math.isfinite(value) and abs(value) <= POSITION_LIMIT
                and value != getattr(self.project.keyframes[self.selected_index], self.channel)):
            self.on_change(self.selected_index, self.channel, value)
        self._sync_value()
        self._redraw()
        return "break"
