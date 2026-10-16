"""Shared desktop camera curves, using the saved Project and normal edit callbacks.

Snapshots, viewport scales and unfinished gestures belong to presentation only.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import math
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from . import ui_theme
from .curve import POSITION_LIMIT, PositionBounds, TimelineView, hit_key, sample_channel
from .path import CURVE_CHANNELS, Project, _unwrap, channel_value
from .ui.widgets import ScrollPage

GROUPS = ("Position", "Rotation", "Framing")
CHANNELS = (("x", "y", "z"), ("pitch", "yaw", "roll"), ("aspect_ratio",))
LABELS = {"x": "X", "y": "Y", "z": "Z", "pitch": "Pitch", "yaw": "Yaw",
          "roll": "Roll", "aspect_ratio": "Aspect ratio"}
TANGENT_MODES = ("auto", "flat", "linked", "broken")


def tangent_times(project, index):
    """Fixed display offsets; dragging a handle never retimes its camera."""
    keys = project.keyframes
    return tuple((keys[index+offset].time-keys[index].time)/3
                 if 0 <= index+offset < len(keys) else None for offset in (-1, 1))


def tangent_handle(bounds, timestamp, value, delta, slope, scale=1.0):
    """A compact direction arm, returning its effective shot-time offset.

    The arm is presentation, not a Bezier time weight. Its screen shortening
    must also shorten the time denominator used by a vertical drag.
    """
    if delta is None or delta == 0 or not math.isfinite(slope):
        return None
    key_x, key_y = bounds.point(timestamp, value)
    inset = 7.0*scale
    if not (bounds.left <= key_x <= bounds.right and bounds.top <= key_y <= bounds.bottom):
        return None
    pixels_per_second = (bounds.right-bounds.left)/bounds.duration
    pixels_per_unit = (bounds.bottom-bounds.top)/(bounds.high-bounds.low)
    dx, dy = delta*pixels_per_second, -delta*slope*pixels_per_unit
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length == 0:
        return None
    ux, uy = dx/length, dy/length
    arm = min(56.0*scale, max(28.0*scale, length))
    # Keep a complete grab target inside the plot, even after time zoom/pan.
    for direction, origin, low, high in ((ux, key_x, bounds.left+inset, bounds.right-inset),
                                         (uy, key_y, bounds.top+inset, bounds.bottom-inset)):
        if direction > 0:
            arm = min(arm, (high-origin)/direction)
        elif direction < 0:
            arm = min(arm, (low-origin)/direction)
    if arm < 18.0*scale:
        return None
    x, y = key_x+ux*arm, key_y+uy*arm
    effective_delta = (x-key_x)/pixels_per_second
    if effective_delta == 0 or not math.isfinite(effective_delta):
        return None
    return x, y, effective_delta


def display_values(project, channel):
    """Evaluator branch coordinates, separate from editable authored angles."""
    values = [channel_value(key, channel) for key in project.keyframes]
    return _unwrap(values) if channel in ("yaw", "roll") and project.rotation_mode == "shortest" else values


def valid_value(channel, value):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            and (.5 <= value <= 4 if channel == "aspect_ratio" else abs(value) <= POSITION_LIMIT))


def branch_offset(project, reference, channel):
    if (reference is None or not reference.keyframes or not project.keyframes
            or channel not in ("yaw", "roll") or project.rotation_mode != "shortest"
            or reference.rotation_mode != "shortest"):
        return 0.0
    turns = (display_values(project,channel)[0]-display_values(reference,channel)[0])/360.0
    # Match C++ round, including the exactly half-turn tie.
    return 360.0*(math.floor(turns+.5) if turns>=0 else math.ceil(turns-.5))


def clipped_paths(bounds, pairs):
    """Clip sampled polylines to the plot, keeping all labels outside them."""
    paths, current = [], []
    points = [bounds.point(time, value) for time, value in pairs]
    for a, b in zip(points, points[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        enter, leave = 0.0, 1.0
        valid = True
        for p, q in ((-dx,a[0]-bounds.left),(dx,bounds.right-a[0]),
                     (-dy,a[1]-bounds.top),(dy,bounds.bottom-a[1])):
            if p == 0:
                if q < 0:
                    valid = False
                    break
            elif p < 0:
                enter = max(enter,q/p)
            else:
                leave = min(leave,q/p)
            if enter > leave:
                valid = False
                break
        if not valid:
            if len(current) > 1:
                paths.append(current)
            current = []
            continue
        first, last = (a[0]+enter*dx,a[1]+enter*dy), (a[0]+leave*dx,a[1]+leave*dy)
        if current and current[-1] == first:
            current.append(last)
        else:
            if len(current) > 1:
                paths.append(current)
            current = [first,last]
    if len(current) > 1:
        paths.append(current)
    return paths


@dataclass
class CurveGesture:
    project: Project
    snapshot: Project
    context: tuple
    index: int
    channel: str
    time: float
    original: float


@dataclass
class TangentGesture:
    project: Project
    snapshot: Project
    context: tuple
    index: int
    channel: str
    time: float
    original: object
    slopes: tuple[float, float]


class CurveWorkspaceState:
    """Revision/session-bound transactions, shared clock and independent scales."""
    def __init__(self, on_change, view=None, on_tangent_change=None):
        self.on_change = on_change
        self.on_tangent_change = on_tangent_change
        self.view = view if view is not None else TimelineView()
        self.project, self.context = Project(), (None, None)
        self.selected, self.enabled, self.current_time = None, True, 0.0
        self.original, self.show_original, self.gesture = None, False, None
        self.scales = {}
        self._scale_signatures = {}
        self._had_cameras = False
        self._angle_state = None
        self._sample_cache = {}
        self._captured_cache = None
        self._captured_signature = None
        self.tangent_error = ""

    def refresh(self, project, selected=None, current_time=0.0, context=None):
        # A caller may refresh an existing Project after an in-place mutation.
        # Cached evaluation is confined to layout/view work between refreshes.
        self._sample_cache.clear()
        self._captured_cache=None
        self._captured_signature=None
        context = self.context if context is None else tuple(context)
        if context[0] != self.context[0]:
            self.original, self.show_original = None, False
            self.frame_all()
        if bool(project.keyframes) != self._had_cameras:
            # The empty-state scale is a placeholder, never a useful range for
            # the first captured camera. Do not carry the old shot's scale back
            # through deleting all cameras either.
            self.scales.clear()
            self._scale_signatures.clear()
        self._had_cameras = bool(project.keyframes)
        self.project, self.context = project, context
        if self.view.end > self.view.start and self.view.start >= (project.duration or 1.0):
            self.view.reset()
        self.selected = (selected if isinstance(selected, int) and not isinstance(selected, bool)
                         and 0 <= selected < len(project.keyframes) else None)
        self.current_time = max(0.0, float(current_time))
        if project.keyframes:
            angles = (project.rotation_mode,display_values(project,"yaw")[0],display_values(project,"roll")[0])
            if self._angle_state is not None:
                for index,channel in enumerate(("yaw","roll"),1):
                    if (angles[0]!=self._angle_state[0] or
                            angles[0]=="shortest" and abs(angles[index]-self._angle_state[index])>=180):
                        self.scales.pop(channel,None)
            self._angle_state = angles
        if self.gesture is not None and not self.current():
            self.cancel()

    def editable(self, index=None, channel=None):
        index = self.selected if index is None else index
        return (self.enabled and isinstance(index, int) and not isinstance(index, bool)
                and 0 <= index < len(self.project.keyframes)
                and self.project.keyframes[index].source == "free"
                and (channel is None or valid_value(channel, channel_value(self.project.keyframes[index], channel))))

    def begin(self, index, channel):
        self.cancel()
        if (not isinstance(index, int) or isinstance(index, bool)
                or channel not in LABELS or not self.editable(index, channel)):
            return False
        key = self.project.keyframes[index]
        self.gesture = CurveGesture(self.project, copy.deepcopy(self.project), self.context,
                                    index, channel, key.time, channel_value(key, channel))
        return True

    def current(self):
        edit = self.gesture
        return (edit is not None and self.editable(edit.index, edit.channel)
                and self.project is edit.project and self.project == edit.snapshot
                and self.context == edit.context and self.selected == edit.index
                and self.project.keyframes[edit.index].time == edit.time)

    def commit(self, value):
        edit = self.gesture
        if (not isinstance(edit, CurveGesture) or not self.current()
                or not valid_value(edit.channel, value)):
            self.cancel()
            return False
        self.cancel()
        if value == edit.original:
            return False
        self.on_change(edit.index, edit.channel, float(value))
        return True

    def tangent_editable(self, index=None, channel=None):
        return (callable(self.on_tangent_change) and self.project.interpolation == "smooth"
                and channel in CHANNELS[0] and self.editable(index, channel))

    def begin_tangent(self, index, channel):
        self.cancel()
        self.tangent_error = ""
        if (not isinstance(index, int) or isinstance(index, bool)
                or not self.tangent_editable(index, channel)):
            return False
        self.gesture = TangentGesture(
            self.project, copy.deepcopy(self.project), self.context, index, channel,
            self.project.keyframes[index].time, self.project.camera_tangent(index, channel),
            self.project.camera_tangent_slopes(index, channel))
        return True

    def tangent_current(self):
        return (isinstance(self.gesture, TangentGesture) and self.current()
                and self.tangent_editable(self.gesture.index, self.gesture.channel))

    def tangent_preview(self, mode, incoming=None, outgoing=None):
        self.tangent_error = ""
        if not self.tangent_current():
            self.cancel()
            return None
        edit = self.gesture
        preview = copy.deepcopy(self.project)
        try:
            preview.set_camera_tangent(edit.index, edit.channel, mode,
                                       incoming=incoming, outgoing=outgoing)
        except (ValueError, TypeError, OverflowError) as error:
            self.tangent_error = str(error)
            return None
        return preview

    def commit_tangent(self, mode, incoming=None, outgoing=None):
        preview = self.tangent_preview(mode, incoming, outgoing)
        edit = self.gesture
        self.cancel()
        if preview is None:
            return False
        tangent = preview.camera_tangent(edit.index, edit.channel)
        if tangent == edit.original:
            return False
        self.on_tangent_change(edit.index, edit.channel, tangent.mode,
                               tangent.incoming, tangent.outgoing)
        return True

    def cancel(self):
        self.gesture = None

    def pin_original(self):
        self.original, self.show_original = copy.deepcopy(self.project), True

    def set_show_original(self, shown):
        if shown and self.original is None:
            self.pin_original()
        self.show_original = bool(shown)

    def frame_all(self):
        self.view.reset()
        self.scales.clear()
        self._scale_signatures.clear()

    def original_offset(self, channel):
        return branch_offset(self.project,self.original,channel)

    def captured_project(self):
        signature=(id(self.project),self.context,self.project.interpolation,self.project.rotation_mode,
                   tuple((key.time,key.pitch,key.yaw,key.roll) for key in self.project.keyframes))
        if self._captured_cache is None or self._captured_signature != signature:
            project = copy.copy(self.project)
            project.keyframes = [replace(key, curve_pitch=None, curve_yaw=None, curve_roll=None)
                                 for key in self.project.keyframes]
            self._captured_cache=project
            self._captured_signature=signature
        return self._captured_cache

    def samples(self,project,channel,start,end):
        interpolation=project.lens_interpolation if channel=="aspect_ratio" else project.interpolation
        key=(id(project),self.context,channel,start,end,interpolation,project.rotation_mode,project.standard_aspect,
             tuple((frame.time,channel_value(frame,channel),frame.tangents.get(channel))
                   for frame in project.keyframes))
        item=self._sample_cache.get(key)
        if item is not None and item[0] is project:
            return item[1]
        values=sample_channel(project,channel,start,end,256)
        if len(self._sample_cache)>=32:
            self._sample_cache.clear()
        # Retain the Project alongside its values: a discarded preview's id
        # cannot be recycled into an unrelated later preview cache hit.
        self._sample_cache[key]=project,values
        return values

    def _scale_signature(self, channel):
        def source(project):
            return (project.lens_interpolation if channel == "aspect_ratio" else project.interpolation,
                    project.rotation_mode, project.standard_aspect,
                    tuple((key.time, channel_value(key, channel), key.tangents.get(channel),
                           getattr(key, channel) if channel in CURVE_CHANNELS else None)
                          for key in project.keyframes))
        return (source(self.project), source(self.original)
                if self.show_original and self.original is not None else None)

    def bounds(self, channel, width, height):
        start, end = self.view.window(self.project.duration or 1.0)
        signature = self._scale_signature(channel)
        if channel not in self.scales or self._scale_signatures.get(channel) != signature:
            values = [value for _, value in self.samples(self.project,channel,start,end)]
            values += display_values(self.project, channel)
            if self.show_original and self.original is not None:
                offset = self.original_offset(channel)
                values += [value + offset for _, value in self.samples(self.original,channel,start,end)]
                values += [value + offset for value in display_values(self.original, channel)]
            if channel in CURVE_CHANNELS:
                captured = self.captured_project()
                offset = branch_offset(self.project,captured,channel)
                values += [value+offset for _, value in self.samples(captured,channel,start,end)]
            low, high = (min(values), max(values)) if values else ((.5, 4) if channel == "aspect_ratio" else (0, 0))
            previous = self.scales.get(channel)
            self._scale_signatures[channel] = signature
            if previous is not None and previous[0] <= low <= high <= previous[1]:
                return PositionBounds(62, 12, max(86, width-16), max(43, height-28),
                                      start, end, *previous)
            if previous is not None:
                low, high = min(low, previous[0]), max(high, previous[1])
            minimum = .08 if channel == "aspect_ratio" else 10 if channel in CHANNELS[0] else 3
            # Existing files can contain finite values outside the editing
            # range. Normalize the fit arithmetic so those stay readable.
            scale = max(abs(low), abs(high), 1.0)
            middle = (low/scale+high/scale)/2
            span = max(high/scale-low/scale, 2*minimum/scale, 1e-12)
            limit = float.fromhex("0x1.fffffffffffffp+1023")/scale
            self.scales[channel] = max(-limit,middle-span*.65)*scale, min(limit,middle+span*.65)*scale
        low, high = self.scales[channel]
        return PositionBounds(62, 12, max(86, width-16), max(43, height-28), start, end, low, high)


class CameraCurveLane(ttk.Frame):
    """One visible channel, sharing the workspace's selection and shot clock."""
    def __init__(self, parent, workspace, group):
        super().__init__(parent, style="Card.TFrame")
        self.workspace, self.group, self.channel = workspace, group, CHANNELS[group][0]
        self._bounds, self._points = None, []
        self._drag_bounds = self._drag_press_y = self._preview = None
        self._drag_value = None
        self._editing_value, self._value_origin = False, None
        self._value_error = ""
        self._pan_x, self._enabled, self._redraw_pending = None, True, False
        self._responsive_width = None
        self._responsive_mode = None
        self._tangent_side = self._tangent_origin = None
        self._tangent_error = ""
        self._handle_side = None
        self._handle_points = {}
        self._handle_delta = None
        self._handle_radius = 9.0
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = self.header = ttk.Frame(self, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        header.columnconfigure(1, weight=1)
        self.title_label = ttk.Label(header,text=GROUPS[group],style="CardMuted.TLabel")
        self.title_label.grid(row=0,column=0,sticky="w",padx=(0,8))
        self.axes = ttk.Frame(header, style="Card.TFrame")
        self.axes.grid(row=0, column=1, sticky="w")
        self.axis_buttons = {}
        for column, name in enumerate(CHANNELS[group] if group < 2 else ()):
            button = ttk.Button(self.axes, text=LABELS[name], width=3 if group == 0 else 6,
                                style="Curve.Axis.TButton", command=lambda name=name: self.set_channel(name))
            button.grid(row=0, column=column, padx=(0, 3))
            self.axis_buttons[name] = button
        if group == 2:
            ttk.Label(self.axes,text="Aspect ratio",style="CardMuted.TLabel").grid(row=0,column=0,sticky="w")
        self.channel_box = ttk.Combobox(header, state="readonly", width=7 if group == 1 else 3,
                                        values=[LABELS[name] for name in CHANNELS[group]])
        self.channel_box.current(0)
        self.channel_box.bind("<<ComboboxSelected>>", self._channel_changed)
        self.reset_button = None
        if group == 1:
            self.reset_button = ttk.Button(header, text="Reset", width=5, style="Quiet.TButton", command=self._reset)
            self.reset_button.grid(row=0, column=2, padx=(5, 6))
        self.value_text = tk.StringVar(self, "")
        self.value_entry = ttk.Entry(header, textvariable=self.value_text, width=12)
        self.value_entry.grid(row=0, column=3, sticky="e")
        units = "units" if group == 0 else "deg" if group == 1 else "ratio"
        self.units_label = ttk.Label(header,text=units,style="CardMuted.TLabel")
        self.units_label.grid(row=0,column=4,padx=(5,0))
        self.value_entry.bind("<FocusIn>", self._begin_value)
        self.value_entry.bind("<Return>", self._apply_value)
        self.value_entry.bind("<Escape>", self._cancel_value)
        self.value_entry.bind("<FocusOut>", self._leave_value)
        self.value_entry.bind("<KeyPress>", self._value_key)
        self.canvas = tk.Canvas(self, background=ui_theme.TOKENS["field"], highlightthickness=0,
                                borderwidth=0, height=145, width=300, takefocus=True)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.hint = ttk.Label(self, style="CardMuted.TLabel")
        self.hint.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.tangent_panel = None
        if group == 0:
            self._build_tangent_controls()
        self.canvas.bind("<Configure>", self._schedule_redraw)
        self.bind("<Configure>", self._responsive, add="+")
        for event, handler in (("<ButtonPress-1>", self._press), ("<B1-Motion>", self._motion),
                               ("<ButtonRelease-1>", self._release), ("<KeyPress-Up>", self._key),
                               ("<KeyPress-Down>", self._key), ("<KeyPress-Escape>", self._cancel),
                               ("<FocusOut>", self._cancel), ("<MouseWheel>", self._wheel),
                               ("<ButtonPress-3>", self._pan_press), ("<B3-Motion>", self._pan_motion)):
            self.canvas.bind(event, handler)
        self.bind("<Unmap>", self._cancel)
        self.canvas.bind("<ButtonRelease-3>", lambda _event: setattr(self, "_pan_x", None))
        self.canvas.bind("<Double-Button-1>", self._double_press)
        self._sync_value()

    def _build_tangent_controls(self):
        panel = self.tangent_panel = ttk.Frame(self, style="Card.TFrame")
        panel.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.tangent_mode = tk.StringVar(self, "Auto")
        self.tangent_mode_box = ttk.Combobox(panel, textvariable=self.tangent_mode,
                                            values=tuple(mode.title() for mode in TANGENT_MODES),
                                            state="readonly", width=8)
        self.tangent_mode_box.bind("<<ComboboxSelected>>", self._change_tangent_mode)
        self.tangent_units = ttk.Label(panel, text="units/s", style="CardMuted.TLabel")
        self.tangent_texts = {}
        self.tangent_entries = {}
        self.tangent_labels = {}
        for side, title in (("incoming", "Arrival"), ("outgoing", "Departure")):
            self.tangent_labels[side] = ttk.Label(panel, text=title, style="CardMuted.TLabel")
            text = self.tangent_texts[side] = tk.StringVar(self, "")
            entry = self.tangent_entries[side] = ttk.Entry(panel, textvariable=text, width=11)
            entry.bind("<FocusIn>", lambda event, side=side: self._begin_tangent_value(side))
            entry.bind("<Return>", self._apply_tangent_value)
            entry.bind("<Escape>", self._cancel_tangent_value)
            entry.bind("<FocusOut>", self._leave_tangent_value)
            entry.bind("<KeyPress>", lambda event, side=side: self._tangent_value_key(side))
        self._layout_tangent_controls(False)

    def _layout_tangent_controls(self, layout):
        narrow = layout > 0
        stacked = layout == 2
        row = 1 if narrow else 0
        self.tangent_mode_box.grid(row=0, column=0, sticky="w", padx=(0, 10),
                                   columnspan=2 if narrow and not stacked else 1)
        for number, side in enumerate(("incoming", "outgoing")):
            column = 0 if stacked else number*2+(0 if narrow else 1)
            self.tangent_labels[side].grid(row=row+number if stacked else row, column=column, sticky="w", padx=(0, 5),
                                           pady=(4, 0) if narrow else 0)
            self.tangent_entries[side].grid(row=row+number if stacked else row, column=column+1, sticky="w", padx=(0, 10),
                                            pady=(4, 0) if narrow else 0)
        self.tangent_units.grid(row=0, column=1 if stacked else 2 if narrow else 5, sticky="w")

    @property
    def state(self):
        return self.workspace.state

    @property
    def project(self):
        return self.state.project

    @property
    def view(self):
        return self.state.view

    @property
    def selected_index(self):
        return self.state.selected

    def set_project(self, project, selected_index=None, current_time=0.0):
        self.workspace.set_project(project, selected_index, current_time)

    def set_enabled(self, enabled):
        self.workspace.set_enabled(enabled)

    def set_current_time(self, current_time):
        self.state.current_time = max(0.0, float(current_time))
        self._draw_playhead()

    def _responsive(self, _event=None):
        width=self.winfo_width()
        if width == self._responsive_width:
            return
        self._responsive_width=width
        fixed = self.title_label.winfo_reqwidth()+self.value_entry.winfo_reqwidth()+self.units_label.winfo_reqwidth()+25
        if self.reset_button is not None:
            fixed += self.reset_button.winfo_reqwidth()+12
        inline = self.group<2 and width>=fixed+self.axes.winfo_reqwidth()
        axis_width = self.axes.winfo_reqwidth() if inline or self.group==2 else self.channel_box.winfo_reqwidth()
        second_row = width<fixed+axis_width
        if (inline,second_row) != self._responsive_mode:
            self._responsive_mode=inline,second_row
            if self.group<2 and not inline:
                self.axes.grid_remove()
                self.channel_box.grid(row=0, column=1, sticky="w")
            elif self.group<2:
                self.channel_box.grid_remove()
                self.axes.grid()
            self.value_entry.grid_configure(row=1 if second_row else 0,column=1 if second_row else 3,
                                             columnspan=2 if second_row else 1,pady=(4,0) if second_row else 0)
            self.units_label.grid_configure(row=1 if second_row else 0,column=3 if second_row else 4)
        self.hint.configure(wraplength=max(140,width-6))
        if self.tangent_panel is not None:
            total = (self.tangent_mode_box.winfo_reqwidth()+self.tangent_units.winfo_reqwidth()+30
                     +sum(widget.winfo_reqwidth()+10 for widget in self.tangent_labels.values())
                     +sum(widget.winfo_reqwidth()+10 for widget in self.tangent_entries.values()))
            pair_width = (sum(widget.winfo_reqwidth()+10 for widget in self.tangent_labels.values())
                          +sum(widget.winfo_reqwidth()+10 for widget in self.tangent_entries.values()))
            self._layout_tangent_controls(2 if width < pair_width else 1 if width < total else 0)
        self.workspace._schedule_measure()

    def _sync_value(self):
        if self._editing_value and not self._value_current():
            self._editing_value, self._value_origin = False, None
            self._value_error = ""
        if not self._editing_value:
            project = (self._preview if self._drag_bounds is not None and self._preview is not None
                       and self.state.current() else self.project)
            key = project.keyframes[self.selected_index] if self.selected_index is not None else None
            self.value_text.set(format(channel_value(key,self.channel),".8g") if key is not None else "")
        enabled = self.state.editable(channel=self.channel)
        self.value_entry.configure(state="normal" if enabled else "disabled")
        for name, button in self.axis_buttons.items():
            button.configure(style="Curve.Selected.Axis.TButton" if name == self.channel else "Curve.Axis.TButton")
        if self.reset_button is not None:
            self.reset_button.configure(state="normal" if self.state.enabled else "disabled")
        reason = ("Pause playback or finish recording to edit" if not self.state.enabled else
                  "Select a camera key" if self.selected_index is None else
                  "Attached camera: edit attachment offsets" if self.project.keyframes[self.selected_index].source != "free" else
                  "Existing authored value exceeds the editor range" if not enabled else
                  self._value_error if self._value_error else
                  "Enter applies; Escape cancels" if self._editing_value else
                  f"Camera {self.selected_index+1:02d} | {self.project.keyframes[self.selected_index].time:.2f} s"+
                  (" | Dotted: captured angles; Reset restores this channel" if self.group==1 else ""))
        self.hint.configure(text=reason,foreground=ui_theme.TOKENS["warn"] if self._value_error else ui_theme.TOKENS["muted"])
        if self.tangent_panel is not None:
            self._sync_tangents()
            if self._tangent_error:
                self.hint.configure(text=self._tangent_error, foreground=ui_theme.TOKENS["warn"])
            elif self.project.interpolation != "smooth":
                self.hint.configure(text=reason+" | Arrival/departure applies in Smooth; saved controls are kept")
            elif self._tangent_side is not None:
                self.hint.configure(text="Slope in units/s | Enter applies; Escape cancels")
        # Stacked graphs share the selected camera and instructions. Keep an
        # individual warning/draft visible, without repeating idle metadata.
        if (self.workspace.stack_var.get() and enabled and not self._editing_value and not self._value_error
                and not self._tangent_error and self._tangent_side is None
                and not (self.group == 0 and self.project.interpolation != "smooth")):
            self.hint.grid_remove()
        else:
            self.hint.grid()

    def _sync_tangents(self):
        if self._tangent_side is not None and not self._tangent_value_current():
            self._tangent_side = self._tangent_origin = None
            self._tangent_error = ""
        index = self.selected_index
        valid = index is not None and 0 <= index < len(self.project.keyframes)
        project = (self._preview if self._handle_side is not None and self._preview is not None
                   and self.state.tangent_current() else self.project)
        tangent = project.camera_tangent(index, self.channel) if valid else None
        enabled = self.state.tangent_editable(index, self.channel)
        self.tangent_mode_box.configure(state="readonly" if enabled else "disabled")
        self.tangent_mode.set(tangent.mode.title() if tangent is not None else "Auto")
        if tangent is None:
            slopes = (None, None)
        elif self.project.interpolation == "smooth":
            slopes = project.camera_tangent_slopes(index, self.channel)
        else:
            slopes = ((0.0, 0.0) if tangent.mode == "flat" else
                      (tangent.incoming, tangent.outgoing))
        for number, side in enumerate(("incoming", "outgoing")):
            available = valid and tangent_times(self.project, index)[number] is not None
            editable = enabled and available and tangent.mode in ("linked", "broken")
            self.tangent_entries[side].configure(state="normal" if editable else "disabled")
            if self._tangent_side != side:
                value = slopes[number] if available else None
                self.tangent_texts[side].set(format(value, ".8g") if value is not None else "")

    def _begin_tangent_value(self, side):
        if (side not in self.tangent_entries or self.selected_index is None
                or tangent_times(self.project, self.selected_index)[0 if side == "incoming" else 1] is None):
            return
        if self._tangent_side == side and self._tangent_value_current():
            return
        self.workspace.clear_preview()
        self.workspace.cancel_edits()
        tangent = (self.project.camera_tangent(self.selected_index, self.channel)
                   if self.selected_index is not None else None)
        if (tangent is not None and tangent.mode in ("linked", "broken")
                and self.state.begin_tangent(self.selected_index, self.channel)):
            self._tangent_side, self._tangent_origin = side, self.state.gesture
            self._tangent_error = ""
            self.tangent_texts[side].set(repr(getattr(tangent, side)))
            self._sync_value()

    def _tangent_value_current(self):
        return (self._tangent_side is not None and self.state.gesture is self._tangent_origin
                and self.state.tangent_current() and self.state.gesture.channel == self.channel)

    def _tangent_value_key(self, side):
        if not self._tangent_value_current():
            self._begin_tangent_value(side)
        self._tangent_error = ""

    def _apply_tangent_value(self, _event=None):
        if not self._tangent_value_current():
            return self._cancel_tangent_value()
        try:
            value = float(self.tangent_texts[self._tangent_side].get())
        except (ValueError, OverflowError):
            value = math.nan
        if not math.isfinite(value):
            self._tangent_error = "Enter a finite slope in units/s; Escape cancels"
            self._sync_value()
            return "break"
        edit = self.state.gesture
        tangent = edit.original
        incoming = value if self._tangent_side == "incoming" else tangent.incoming
        outgoing = value if self._tangent_side == "outgoing" else tangent.outgoing
        if tangent.mode == "linked":
            incoming = outgoing = value
        if self.state.tangent_preview(tangent.mode, incoming, outgoing) is None:
            if not self.state.tangent_current():
                return self._cancel_tangent_value()
            self._tangent_error = self.state.tangent_error or "This slope cannot be represented safely"
            self._sync_value()
            return "break"
        self._tangent_side = self._tangent_origin = None
        self._tangent_error = ""
        self.state.commit_tangent(tangent.mode, incoming, outgoing)
        self.workspace.redraw()
        return "break"

    def _leave_tangent_value(self, _event=None):
        if self._tangent_side is not None:
            return self._apply_tangent_value()

    def _cancel_tangent_value(self, _event=None):
        if self.state.gesture is self._tangent_origin:
            self.state.cancel()
        self._tangent_side = self._tangent_origin = None
        self._tangent_error = ""
        if self.tangent_panel is not None:
            self._sync_value()
        return "break"

    def _change_tangent_mode(self, _event=None):
        self.workspace.clear_preview()
        mode = self.tangent_mode.get().lower()
        self.workspace.cancel_edits()
        if mode not in TANGENT_MODES or not self.state.begin_tangent(self.selected_index, self.channel):
            self.workspace.redraw()
            return "break"
        edit = self.state.gesture
        incoming, outgoing = edit.slopes
        if mode == "linked":
            # A shared slope starts with the side present at an endpoint, or
            # arrival at an interior key. Choosing Linked must not invent a stop.
            incoming = outgoing = incoming if edit.index > 0 else outgoing
        if mode in ("auto", "flat"):
            incoming = outgoing = None
        if self.state.tangent_preview(mode, incoming, outgoing) is None:
            self._tangent_error = self.state.tangent_error or "This slope cannot be represented safely"
            self.state.cancel()
            self.workspace.redraw()
            return "break"
        self.state.commit_tangent(mode, incoming, outgoing)
        self.workspace.redraw()
        return "break"

    def set_channel(self, channel):
        if channel not in CHANNELS[self.group] or channel == self.channel:
            return
        self._cancel()
        self.channel = channel
        self.channel_box.current(CHANNELS[self.group].index(channel))
        self._sync_value()
        self._redraw()

    def _channel_changed(self, _event=None):
        index = self.channel_box.current()
        if 0 <= index < len(CHANNELS[self.group]):
            self.set_channel(CHANNELS[self.group][index])

    def _reset(self):
        if self.workspace.settle_numeric() and self.state.enabled:
            self.workspace.on_reset(self.channel)

    def _begin_value(self, _event=None):
        if self._value_current():
            return
        self.workspace.clear_preview()
        if self.state.begin(self.selected_index, self.channel):
            self._editing_value, self._value_origin = True, self.state.gesture
            self._value_error = ""
            # Idle formatting is presentation only. Every edit starts from the
            # exact authored double, so focus/Enter cannot round the saved key.
            self.value_text.set(repr(self.state.gesture.original))
            self._sync_value()

    def _value_key(self, _event=None):
        if not self._editing_value:
            self._begin_value()
        self._value_error = ""

    def _leave_value(self,_event=None):
        if self._editing_value:
            return self._apply_value()
        return "break"

    def _value_current(self):
        return (self._editing_value and self.state.gesture is self._value_origin
                and self.state.current() and self.state.gesture.channel == self.channel)

    def _apply_value(self, _event=None):
        if not self._value_current():
            self._cancel_value()
            return "break"
        try:
            value = float(self.value_text.get())
        except (ValueError, OverflowError):
            value = math.nan
        if not valid_value(self.channel, value):
            self._value_error = ("Enter a finite value from 0.5 to 4" if self.group==2 else
                                 "Enter a finite value within 100 million")
            self._sync_value()
            return "break"
        self._editing_value, self._value_origin = False, None
        self._value_error = ""
        self.state.commit(value)
        self.workspace.redraw()
        return "break"

    def _cancel_value(self, _event=None):
        if self._editing_value and self.state.gesture is self._value_origin:
            self.state.cancel()
        self._editing_value, self._value_origin = False, None
        self._value_error = ""
        if hasattr(self, "value_text"):
            self._sync_value()
        return "break"

    def _schedule_redraw(self, _event=None):
        self.workspace.schedule_redraw()

    def _scheduled_redraw(self):
        self._redraw_pending = False
        if self.winfo_exists():
            self._redraw()

    def _redraw(self, _event=None):
        if not hasattr(self, "canvas"):
            return
        self._sync_value()
        canvas = self.canvas
        canvas.delete("all")
        self._handle_points = {}
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 110 or height < 65:
            return
        bounds = self._drag_bounds or self.state.bounds(self.channel, width, height)
        self._bounds = bounds
        colors = ui_theme.TOKENS
        font = (ui_theme.FONT_FAMILY, ui_theme.FONT_SIZES["tiny"])
        def value_labels():
            for index in range(3):
                y = bounds.top+(bounds.bottom-bounds.top)*index/2
                value = bounds.value_at(y)
                label = (f"{value:.3f}" if self.group == 2 else f"{value:.1f}" if abs(value)<10000 else
                         f"{value:.0f}" if abs(value)<1e10 else f"{value:.4g}")
                canvas.create_text(bounds.left-8, y, text=label, anchor="e", fill=colors["muted"], font=font)
        for index in range(3):
            y = bounds.top + (bounds.bottom-bounds.top)*index/2
            canvas.create_line(bounds.left, y, bounds.right, y, fill=colors["edge"])
        for index in range(5):
            timestamp = bounds.start + bounds.duration*index/4
            x = bounds.point(timestamp, bounds.low)[0]
            canvas.create_line(x, bounds.top, x, bounds.bottom, fill=colors["edge"])
        value_labels()
        if not self.project.keyframes:
            canvas.create_text((bounds.left+bounds.right)/2, (bounds.top+bounds.bottom)/2,
                               text="Capture a camera to start a curve", fill=colors["muted"], font=font)
            self._points = []
            return
        accent = colors["curve_"+self.channel] if self.group == 0 else colors["curve_rotation"] if self.group == 1 else colors["accent"]
        def line(project, color, dash=None, offset=0.0, width=1, tag="curve"):
            pairs = self.state.samples(project,self.channel,bounds.start,bounds.end)
            for path in clipped_paths(bounds,[(time,value+offset) for time,value in pairs]):
                coordinates = [coordinate for point in path for coordinate in point]
                canvas.create_line(*coordinates, fill=color, width=width, dash=dash, tags=tag)
        if self.state.show_original and self.state.original is not None:
            # Canvas lines have no alpha: blend against the exact plot surface.
            before = self._blend(colors["curve_before"], colors["field"], .38)
            line(self.state.original, before, (5, 5), self.state.original_offset(self.channel), tag="original")
        if self.group == 1:
            captured = self.state.captured_project()
            line(captured,colors["muted"],(1,5),branch_offset(self.project,captured,self.channel),tag="captured")
        if self.group == 2 and bounds.low <= self.project.standard_aspect <= bounds.high:
            y = bounds.point(bounds.start, self.project.standard_aspect)[1]
            canvas.create_line(bounds.left, y, bounds.right, y, fill=colors["muted"], dash=(1, 5))
        project = self._preview or self.project
        draft_offset = branch_offset(self.project,project,self.channel) if self._preview is not None else 0.0
        line(project,accent,offset=draft_offset,width=2,tag="current")
        self._draw_tangent_handles(project, bounds, accent)
        self._points = [bounds.point(key.time,value+draft_offset)
                        for key,value in zip(project.keyframes,display_values(project,self.channel))]
        for index, (x, y) in enumerate(self._points):
            if not bounds.left <= x <= bounds.right or not bounds.top <= y <= bounds.bottom:
                continue
            radius = 5 if index == self.selected_index else 3
            fill = colors["text"] if index == self.selected_index else colors["field"]
            canvas.create_polygon(x, y-radius, x+radius, y, x, y+radius, x-radius, y,
                                  fill=fill, outline=accent, width=1.5, tags="keys")
        # Mask overflow, then redraw gutter labels so sampled paths cannot
        # run behind them. Canvas itself clips outside the drawing surface.
        canvas.create_rectangle(0, 0, bounds.left-1, height, fill=colors["field"], outline="", tags="mask")
        value_labels()
        if self.workspace.last_visible_lane() is self:
            for index in range(5):
                timestamp = bounds.start+bounds.duration*index/4
                x = bounds.point(timestamp,bounds.low)[0]
                canvas.create_text(x,bounds.bottom+14,text=f"{timestamp:.2f}s",
                                   anchor="w" if index==0 else "e" if index==4 else "center",
                                   fill=colors["muted"],font=font,tags="time-label")
        self._draw_playhead()

    def _draw_tangent_handles(self, project, bounds, accent):
        index = self.selected_index
        if self.group != 0 or not self.state.tangent_editable(index, self.channel):
            return
        key = project.keyframes[index]
        value = channel_value(key, self.channel)
        scale = max(.75, min(3.0, float(self.tk.call("tk", "scaling"))/(4/3)))
        self._handle_radius = 9*scale
        other_keys = [bounds.point(other.time, channel_value(other, self.channel))
                      for number, other in enumerate(project.keyframes) if number != index]
        key_x, key_y = bounds.point(key.time, value)
        arm_color = self._blend(accent, ui_theme.TOKENS["field"], .65)
        for side, delta, slope in zip(("incoming", "outgoing"), tangent_times(project, index),
                                      project.camera_tangent_slopes(index, self.channel)):
            if side == self._handle_side and self._handle_delta is not None:
                delta = self._handle_delta
                x, y = bounds.point(key.time+delta, value+delta*slope)
                handle = (x, y, delta) if math.isfinite(y) else None
            else:
                handle = tangent_handle(bounds, key.time, value, delta, slope, scale)
            if handle is None:
                continue
            x, y, delta = handle
            if any((x-other_x)**2+(y-other_y)**2 < (21*scale)**2
                   for other_x, other_y in other_keys):
                continue
            for path in clipped_paths(bounds, [(key.time, value),
                                               (key.time+delta, value+delta*slope)]):
                self.canvas.create_line(*(coordinate for point in path for coordinate in point),
                                        fill=arm_color, width=max(1, scale), tags="tangent-line")
            if (bounds.left <= x <= bounds.right and bounds.top <= y <= bounds.bottom
                    and (x-key_x)**2+(y-key_y)**2 >= (18*scale)**2):
                self._handle_points[side] = x, y, delta
                radius = 3*scale
                self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                                        fill=ui_theme.TOKENS["field"], outline=accent,
                                        width=1.5, tags=("tangent-handle", "tangent-"+side))

    @staticmethod
    def _blend(foreground, background, alpha):
        values = [round(int(foreground[i:i+2],16)*alpha+int(background[i:i+2],16)*(1-alpha)) for i in (1,3,5)]
        return "#"+"".join(f"{value:02x}" for value in values)

    def _draw_playhead(self):
        self.canvas.delete("playhead")
        if self._bounds is not None and self._bounds.start <= self.state.current_time <= self._bounds.end:
            x = self._bounds.point(self.state.current_time, self._bounds.low)[0]
            self.canvas.create_line(x, self._bounds.top, x, self._bounds.bottom,
                                    fill=ui_theme.TOKENS["accent"], dash=(2,4), tags="playhead")

    def _press(self, event):
        if not self.state.enabled:
            return
        self.canvas.focus_set()
        self.workspace.cancel_edits()
        for side, (x, y, delta) in self._handle_points.items():
            if ((event.x-x)**2+(event.y-y)**2 <= self._handle_radius**2
                    and self.state.begin_tangent(self.selected_index, self.channel)):
                self._handle_side, self._handle_delta = side, delta
                self._drag_bounds, self._drag_press_y = self._bounds, event.y
                return "break"
        index = hit_key(self._points, event.x, event.y)
        if index is None or self._bounds is None or not self._bounds.top <= event.y <= self._bounds.bottom:
            return
        self.workspace.select(index)
        if self.state.begin(index, self.channel):
            self._drag_bounds, self._drag_press_y = self._bounds, event.y
        self._redraw()

    def _double_press(self, event):
        # Tk substitutes Double-Button for the second ordinary press. A quick
        # click to select, then a drag, must still start an editable gesture.
        if (hit_key(self._points, event.x, event.y) is not None
                or any((event.x-x)**2+(event.y-y)**2 <= self._handle_radius**2
                       for x, y, _delta in self._handle_points.values())):
            self._press(event)
        else:
            self.workspace.frame_all()
        return "break"

    def _motion(self, event):
        if self._drag_bounds is None:
            return
        if self._handle_side is not None:
            return self._move_tangent_handle(event)
        if not self.state.current() or self.state.gesture.channel != self.channel:
            self._cancel()
            return
        edit = self.state.gesture
        value = edit.original + (self._drag_bounds.value_at(event.y)-self._drag_bounds.value_at(self._drag_press_y))
        if not math.isfinite(value):
            self._cancel()
            return
        value = max(.5,min(4,value)) if self.group == 2 else value
        if not valid_value(self.channel, value):
            self._cancel()
            return
        self._preview = copy.copy(self.project)
        self._preview.keyframes = list(self.project.keyframes)
        field = "curve_"+self.channel if self.group == 1 else self.channel
        self._preview.keyframes[edit.index] = replace(self.project.keyframes[edit.index], **{field:value})
        try:
            self._preview.validate()
        except (ValueError, TypeError, OverflowError) as error:
            self._preview = self._drag_value = None
            self._value_error = str(error)
            self.workspace.offer_preview(None, edit)
            self._redraw()
            return
        self._value_error = ""
        self._drag_value = value
        self.workspace.offer_preview(self._preview, edit)
        self._redraw()

    def _move_tangent_handle(self, event):
        if not self.state.tangent_current():
            return self._cancel()
        edit = self.state.gesture
        value_delta = (self._drag_bounds.value_at(event.y)
                       -self._drag_bounds.value_at(self._drag_press_y))
        slopes = list(edit.slopes)
        side = 0 if self._handle_side == "incoming" else 1
        slope = slopes[side]+value_delta/self._handle_delta
        if not math.isfinite(slope):
            return self._cancel()
        slopes[side] = slope
        mode = "linked" if edit.original.mode == "linked" else "broken"
        if mode == "linked":
            slopes = [slope, slope]
        preview = self.state.tangent_preview(mode, *slopes)
        if preview is None:
            error = self.state.tangent_error or "This slope cannot be represented safely"
            self._cancel()
            self._tangent_error = error
            self._sync_value()
            return "break"
        # A zero pointer delta must retain Auto/Flat absence exactly.
        self._drag_value = (mode, *slopes) if value_delta != 0 else None
        self._preview = preview if value_delta != 0 else None
        self.workspace.offer_preview(self._preview or self.project, edit)
        self._redraw()
        return "break"

    def _release(self, _event=None):
        if self._drag_bounds is None:
            return
        self.workspace.clear_preview()
        value = self._drag_value
        tangent = self._handle_side is not None
        self._handle_side = self._handle_delta = None
        self._drag_bounds = self._drag_press_y = self._drag_value = self._preview = None
        if value is not None:
            if tangent:
                self.state.commit_tangent(*value)
            else:
                self.state.commit(value)
        else:
            self.state.cancel()
        self.workspace.redraw()

    def _cancel(self, _event=None):
        self.workspace.clear_preview()
        self._drag_bounds = self._drag_press_y = self._preview = self._drag_value = None
        self._handle_side = self._handle_delta = None
        self.state.cancel()
        self._cancel_value()
        self._cancel_tangent_value()
        if hasattr(self,"canvas"):
            self._redraw()
        return "break"

    def _key(self, event):
        if self._drag_bounds is not None or not self.state.begin(self.selected_index,self.channel):
            return "break"
        increment = (.1 if event.state & 1 else .01) if self.group == 2 else (10 if event.state & 1 else 1)
        if event.keysym == "Down":
            increment = -increment
        value = self.state.gesture.original+increment
        if self.group == 2:
            value = round(max(.5,min(4,value)),4)
        self.state.commit(value)
        self.workspace.redraw()
        return "break"

    def _wheel(self,event):
        if self._bounds is None or not self.workspace.settle_numeric():
            return "break"
        self.workspace.cancel_edits()
        fraction=(min(max(event.x,self._bounds.left),self._bounds.right)-self._bounds.left)/max(1,self._bounds.right-self._bounds.left)
        start,end=self.view.window(self.project.duration or 1)
        previous=self.view.start,self.view.end
        self.view.zoom(.85**(event.delta/120),start+(end-start)*fraction,self.project.duration or 1)
        if self.view.window(self.project.duration or 1) != (start,end):
            self.workspace.schedule_redraw()
        else:
            self.view.start,self.view.end=previous
        return "break"

    def _pan_press(self,event):
        if self._drag_bounds is not None or self._tangent_side is not None:
            return self._cancel()
        if self._bounds is not None and self.workspace.settle_numeric():
            self.workspace.cancel_edits()
            self._pan_x = event.x

    def _pan_motion(self,event):
        if self._pan_x is not None and self._bounds is not None:
            self.view.pan(-(event.x-self._pan_x)/max(1,self._bounds.right-self._bounds.left)*self._bounds.duration,
                          self.project.duration or 1)
            self._pan_x = event.x
            self.workspace.schedule_redraw()


class CameraCurveColumn(ScrollPage):
    """Keep the list and a readable curve reachable on short/high-DPI screens."""
    def __init__(self, parent):
        super().__init__(parent)
        self.body.configure(padding=0)
        self._panels = None
        self._sizing = False
        self._content_size = None
        self.canvas.bind("<Configure>", self.resize_content)
        self.body.bind("<Configure>", self.resize_content)

    def set_panels(self, table, graph, header, curves):
        self._panels = table, graph, header, curves
        curves.set_scroll_owner(self)
        curves.on_geometry = self.resize_content
        self.resize_content()

    def resize_content(self, _event=None):
        if self._panels is None or self._sizing:
            return
        self._sizing = True
        try:
            table, graph, header, curves = self._panels
            padding = [int(value) for value in self.tk.splitlist(graph.cget("padding"))]
            graph_padding = padding[1]+padding[3] if len(padding)==4 else padding[-1]*2 if padding else 0
            minimum = table.winfo_reqheight()+10+header.winfo_reqheight()+4+graph_padding+curves.minimum_height()
            width, available = max(1,self.canvas.winfo_width()), max(1,self.canvas.winfo_height())
            height = max(available,minimum)
            if self._content_size != (width,height):
                self._content_size=width,height
                self.canvas.itemconfigure(self.window,width=width,height=height)
                self.canvas.configure(scrollregion=(0,0,width,height))
        finally:
            self._sizing = False


class CameraCurveWorkspace(ttk.Frame):
    def __init__(self,parent,*,on_change,on_select,on_reset,context,view=None,on_tangent_change=None,
                 on_preview=None):
        super().__init__(parent,style="Card.TFrame")
        self.on_select,self.on_reset,self.get_context = on_select,on_reset,context
        self.state = CurveWorkspaceState(on_change,view,on_tangent_change)
        self.on_preview = on_preview
        self._preview_gesture = None
        self.graph_font = tkfont.Font(self,font=(ui_theme.FONT_FAMILY,ui_theme.FONT_SIZES["tiny"]))
        self.on_geometry = None
        self._measure_pending = False
        self._measure_after = None
        self._redraw_after = None
        self._scroll_owner = None
        self._body_size = None
        self._responsive_mode = None
        self.group = 0
        self.stack_var = tk.BooleanVar(self,False)
        self.original_var = tk.BooleanVar(self,False)
        self.lane_vars = [tk.BooleanVar(self,index<2) for index in range(3)]
        self.columnconfigure(0,weight=1)
        self.rowconfigure(2,weight=1)
        top = self.top = ttk.Frame(self,style="Card.TFrame")
        top.grid(row=0,column=0,sticky="ew",pady=(0,5))
        self.tabs = ttk.Frame(top,style="Card.TFrame")
        self.tabs.pack(side="left")
        self.tab_buttons=[]
        for group,label in enumerate(GROUPS):
            button=ttk.Button(self.tabs,text=label,style="Curve.Axis.TButton",command=lambda group=group:self.select_group(group))
            button.pack(side="left",padx=(0,3))
            self.tab_buttons.append(button)
        self.graphs_button=ttk.Menubutton(top,text="Graphs")
        self.graphs_menu=tk.Menu(self.graphs_button,tearoff=False,background=ui_theme.TOKENS["panel"],
                                 foreground=ui_theme.TOKENS["text"],activebackground=ui_theme.TOKENS["selected"],
                                 activeforeground=ui_theme.TOKENS["text"])
        for group,label in enumerate(GROUPS):
            self.graphs_menu.add_checkbutton(label=label,variable=self.lane_vars[group],command=lambda group=group:self._lanes_changed(group))
        self.graphs_button.configure(menu=self.graphs_menu)
        self.stack_check = ttk.Checkbutton(top,text="Stack graphs",variable=self.stack_var,command=self._layout)
        self.stack_check.pack(side="right")
        tools=self.tools=ttk.Frame(self,style="Card.TFrame")
        tools.grid(row=1,column=0,sticky="ew",pady=(0,7))
        self.original_check=ttk.Checkbutton(tools,text="Show original",variable=self.original_var,command=self._show_original)
        self.original_check.pack(side="left")
        self.update_original_button=ttk.Button(tools,text="Update original",style="Quiet.TButton",command=self.update_original)
        self.update_original_button.pack(side="left",padx=(8,0))
        self.frame_all_button=ttk.Button(tools,text="Frame all",style="Quiet.TButton",command=self.frame_all)
        self.frame_all_button.pack(side="right")
        # Run before ttk focus/press handling so view actions settle a valid
        # draft instead of silently cancelling it when they take focus.
        for widget in (self.frame_all_button,self.update_original_button,self.original_check):
            widget.bind("<ButtonPress-1>",self._settle_view_press,add="+")
        holder=ttk.Frame(self,style="Card.TFrame")
        holder.grid(row=2,column=0,sticky="nsew")
        holder.columnconfigure(0,weight=1)
        holder.rowconfigure(0,weight=1)
        self.scroll_canvas=tk.Canvas(holder,background=ui_theme.TOKENS["panel"],highlightthickness=0,borderwidth=0)
        self.scroll_canvas.grid(row=0,column=0,sticky="nsew")
        self.scrollbar=ttk.Scrollbar(holder,orient="vertical",command=self.scroll_canvas.yview)
        self.scrollbar.grid(row=0,column=1,sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body=ttk.Frame(self.scroll_canvas,style="Card.TFrame")
        self.body.columnconfigure(0,weight=1)
        self.body_window=self.scroll_canvas.create_window(0,0,anchor="nw",window=self.body)
        self.lanes=tuple(CameraCurveLane(self.body,self,group) for group in range(3))
        self.footer=ttk.Label(self,text="Drag keys | Up/Down fine tune | Wheel zoom | Right-drag pan",
                              style="CardMuted.TLabel")
        self.footer.grid(row=3,column=0,sticky="ew",pady=(6,0))
        self.scroll_canvas.bind("<Configure>",self._size_body)
        self.bind("<Configure>",self._responsive,add="+")
        self.bind("<Map>",lambda _event:self.schedule_redraw(),add="+")
        self._layout()

    def visible_groups(self):
        return tuple(index for index,value in enumerate(self.lane_vars) if value.get()) if self.stack_var.get() else (self.group,)

    def last_visible_lane(self):
        return self.lanes[self.visible_groups()[-1]]

    def minimum_height(self):
        # The inner scroll region may contain several graphs. The outer Camera
        # page always reserves room for at least one useful graph below its UI.
        minimum_graph = 5*self.graph_font.metrics("linespace")+40
        heights=self._lane_minimums(minimum_graph)
        body_height=sum(heights[group] for group in self.visible_groups()) if self._scroll_owner is not None else max(heights)
        return self.top.winfo_reqheight()+5+self.tools.winfo_reqheight()+7+body_height+self.footer.winfo_reqheight()+6

    def _lane_minimums(self,minimum_graph):
        return [lane.header.winfo_reqheight()+
                (lane.hint.winfo_reqheight()+4 if lane.hint.winfo_manager() else 0)+
                (lane.tangent_panel.winfo_reqheight()+6 if lane.tangent_panel is not None else 0)+minimum_graph+9
                for lane in self.lanes]

    def set_scroll_owner(self,owner):
        self._scroll_owner=owner
        self.scrollbar.grid_remove()
        self._body_size=None
        self._schedule_measure()

    def _responsive(self,_event=None):
        stacked = self.stack_var.get()
        left = self.graphs_button if stacked else self.tabs
        split = self.winfo_width() < left.winfo_reqwidth()+self.stack_check.winfo_reqwidth()+12
        split_tools = self.winfo_width() < (self.original_check.winfo_reqwidth()+self.update_original_button.winfo_reqwidth()+self.frame_all_button.winfo_reqwidth()+20)
        if (stacked,split,split_tools) != self._responsive_mode:
            self._responsive_mode=stacked,split,split_tools
            # Only mode changes rewrite geometry; position/height Configure
            # events while scrolling cannot recursively reflow these rows.
            left.pack_forget()
            self.stack_check.pack_forget()
            self.top.columnconfigure(0,weight=1)
            left.grid(row=0,column=0,sticky="w")
            self.stack_check.grid(row=1 if split else 0,column=0 if split else 1,sticky="w" if split else "e",pady=(4,0) if split else 0)
            for widget in (self.original_check,self.update_original_button,self.frame_all_button):
                widget.pack_forget()
            self.tools.columnconfigure(1,weight=1)
            self.original_check.grid(row=0,column=0,sticky="w")
            self.update_original_button.grid(row=0,column=1,sticky="w",padx=(8,0))
            self.frame_all_button.grid(row=1 if split_tools else 0,column=0 if split_tools else 2,
                                      sticky="w" if split_tools else "e",pady=(4,0) if split_tools else 0)
        self.footer.configure(wraplength=max(180,self.winfo_width()-6))
        self._schedule_measure()

    def _size_body(self,_event=None):
        available=max(1,self.scroll_canvas.winfo_height())
        minimum_graph=5*self.graph_font.metrics("linespace")+40
        minimums=self._lane_minimums(minimum_graph)
        minimum=sum(minimums[group] for group in self.visible_groups())
        if self._scroll_owner is not None and self.grid_rowconfigure(2)['minsize'] != minimum:
            self.rowconfigure(2,minsize=minimum)
        height=max(available,minimum)
        width=max(1,self.scroll_canvas.winfo_width())
        if self._body_size != (width,height):
            self._body_size=width,height
            self.scroll_canvas.itemconfigure(self.body_window,width=width,height=height)
            self.scroll_canvas.configure(scrollregion=(0,0,width,height))
        if self._scroll_owner is not None or height<=available:
            if self.scrollbar.winfo_manager():self.scrollbar.grid_remove()
        elif not self.scrollbar.winfo_manager():
            self.scrollbar.grid()
        if self.on_geometry is not None:
            self.on_geometry()

    def _schedule_measure(self):
        if not self._measure_pending:
            self._measure_pending=True
            self._measure_after=self.after_idle(self._measure)

    def _measure(self):
        self._measure_pending=False
        self._measure_after=None
        if self.winfo_exists():
            self._size_body()

    def destroy(self):
        self.clear_preview()
        if self._measure_after is not None:
            self.after_cancel(self._measure_after)
            self._measure_after=None
        if self._redraw_after is not None:
            self.after_cancel(self._redraw_after)
            self._redraw_after=None
        super().destroy()

    def schedule_redraw(self):
        if self._redraw_after is None:
            self._redraw_after=self.after_idle(self._redraw_scheduled)

    def _redraw_scheduled(self):
        self._redraw_after=None
        self.redraw()

    def _layout(self):
        self.cancel_edits()
        if self.stack_var.get():
            self.tabs.pack_forget()
            self.tabs.grid_remove()
        else:
            self.graphs_button.pack_forget()
            self.graphs_button.grid_remove()
        for group,button in enumerate(self.tab_buttons):
            button.configure(style="Curve.Selected.Axis.TButton" if group==self.group else "Curve.Axis.TButton")
        for lane in self.lanes:
            lane.grid_remove()
        for row in range(3):
            self.body.rowconfigure(row,weight=0)
        groups=self.visible_groups()
        for row,group in enumerate(groups):
            self.body.rowconfigure(row,weight=1)
            self.lanes[group].grid(row=row,column=0,sticky="nsew",pady=(0,8 if row<len(groups)-1 else 0))
        self._size_body()
        self.redraw()
        self._responsive()

    def select_group(self,group):
        if group in range(3):
            self.group=group
            self._layout()

    def _lanes_changed(self,changed):
        if not any(value.get() for value in self.lane_vars):
            self.lane_vars[changed].set(True)
        self._layout()

    def set_project(self,project,selected_index=None,current_time=0.0):
        self.state.refresh(project,selected_index,current_time,self.get_context())
        if self._preview_gesture is not None and (self.state.gesture is not self._preview_gesture
                                                  or not self.state.current()):
            self.cancel_edits()
        self.original_var.set(self.state.show_original)
        self.redraw()

    def set_enabled(self,enabled):
        changed = self.state.enabled != bool(enabled)
        self.state.enabled=bool(enabled)
        if not self.state.enabled:
            self.cancel_edits()
        for lane in self.lanes:
            lane._enabled=self.state.enabled
            lane._sync_value()
        if changed:
            self._schedule_measure()

    def select(self,index):
        if index != self.state.selected:
            self.cancel_edits()
        self.state.selected=index
        self.on_select(index)
        self.redraw()

    def redraw(self):
        if self._redraw_after is not None:
            self.after_cancel(self._redraw_after)
            self._redraw_after=None
        self.update_original_button.configure(state="normal" if self.state.original is not None else "disabled")
        legend = " | Solid: current; dashed: original" if self.state.show_original else ""
        if self.stack_var.get() and 1 in self.visible_groups():
            legend += " | Dotted: captured rotation; Reset restores this channel"
        if 0 in self.visible_groups() and self.state.project.interpolation == "smooth":
            legend += " | Round handles: arrival/departure; right-click or Escape cancels"
        self.footer.configure(text="Drag keys | Up/Down fine tune | Wheel zoom | Right-drag pan"+legend,
                              wraplength=max(180,self.winfo_width()-6))
        for group,lane in enumerate(self.lanes):
            if group in self.visible_groups() and self.winfo_ismapped():
                lane._redraw()
            else:
                lane._sync_value()
        self._schedule_measure()

    def cancel_edits(self):
        self.clear_preview()
        self.state.cancel()
        for lane in getattr(self,"lanes",()):
            lane._editing_value,lane._value_origin=False,None
            lane._value_error=""
            lane._drag_bounds=lane._drag_press_y=lane._preview=lane._drag_value=None
            lane._tangent_side=lane._tangent_origin=None
            lane._tangent_error=""
            lane._handle_side=lane._handle_delta=None

    def offer_preview(self, project, gesture):
        """Offer an already validated local draft; transport owns its cadence."""
        if gesture is not self.state.gesture or not self.state.current():
            self.clear_preview()
            return
        self._preview_gesture = gesture
        if callable(self.on_preview):
            self.on_preview(project, gesture)

    def clear_preview(self):
        if self._preview_gesture is not None:
            self._preview_gesture = None
            if callable(self.on_preview):
                self.on_preview(None, None)

    def settle_numeric(self):
        for lane in self.lanes:
            if lane._editing_value:
                lane._apply_value()
                if lane._editing_value:
                    return False
            if lane._tangent_side is not None:
                lane._apply_tangent_value()
                if lane._tangent_side is not None:
                    return False
        return True

    def _settle_view_press(self,_event=None):
        return None if self.settle_numeric() else "break"

    def frame_all(self):
        if self.settle_numeric():
            self.cancel_edits()
            self.state.frame_all()
            self.redraw()

    def _show_original(self):
        if self.settle_numeric():
            self.state.set_show_original(self.original_var.get())
            self.redraw()

    def update_original(self):
        if self.settle_numeric():
            self.state.pin_original()
            self.original_var.set(True)
            self.redraw()
