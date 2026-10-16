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


class CurveWorkspaceState:
    """Revision/session-bound transactions, shared clock and independent scales."""
    def __init__(self, on_change, view=None):
        self.on_change = on_change
        self.view = view if view is not None else TimelineView()
        self.project, self.context = Project(), (None, None)
        self.selected, self.enabled, self.current_time = None, True, 0.0
        self.original, self.show_original, self.gesture = None, False, None
        self.scales = {}
        self._angle_state = None
        self._sample_cache = {}
        self._captured_cache = None
        self._captured_signature = None

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
        if not self.current() or not valid_value(edit.channel, value):
            self.cancel()
            return False
        self.cancel()
        if value == edit.original:
            return False
        self.on_change(edit.index, edit.channel, float(value))
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
             tuple((frame.time,channel_value(frame,channel)) for frame in project.keyframes))
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

    def bounds(self, channel, width, height):
        start, end = self.view.window(self.project.duration or 1.0)
        if channel not in self.scales:
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
        self.canvas.bind("<Double-Button-1>", lambda _event: self.workspace.frame_all())
        self._sync_value()

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
        self.workspace._schedule_measure()

    def _sync_value(self):
        if self._editing_value and not self._value_current():
            self._editing_value, self._value_origin = False, None
            self._value_error = ""
        if not self._editing_value:
            key = self.project.keyframes[self.selected_index] if self.selected_index is not None else None
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
        # Stacked graphs share the selected camera and instructions. Keep an
        # individual warning/draft visible, without repeating idle metadata.
        if self.workspace.stack_var.get() and enabled and not self._editing_value and not self._value_error:
            self.hint.grid_remove()
        else:
            self.hint.grid()

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
        index = hit_key(self._points, event.x, event.y)
        if index is None or self._bounds is None or not self._bounds.top <= event.y <= self._bounds.bottom:
            return
        self.workspace.select(index)
        if self.state.begin(index, self.channel):
            self._drag_bounds, self._drag_press_y = self._bounds, event.y
        self._redraw()

    def _motion(self, event):
        if self._drag_bounds is None:
            return
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
        self._drag_value = value
        self._redraw()

    def _release(self, _event=None):
        if self._drag_bounds is None:
            return
        value = self._drag_value
        self._drag_bounds = self._drag_press_y = self._drag_value = self._preview = None
        if value is not None:
            self.state.commit(value)
        else:
            self.state.cancel()
        self.workspace.redraw()

    def _cancel(self, _event=None):
        self._drag_bounds = self._drag_press_y = self._preview = self._drag_value = None
        self.state.cancel()
        self._cancel_value()
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
    def __init__(self,parent,*,on_change,on_select,on_reset,context,view=None):
        super().__init__(parent,style="Card.TFrame")
        self.on_select,self.on_reset,self.get_context = on_select,on_reset,context
        self.state = CurveWorkspaceState(on_change,view)
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
                (lane.hint.winfo_reqheight()+4 if lane.hint.winfo_manager() else 0)+minimum_graph+9
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
        self.footer.configure(text="Drag keys | Up/Down fine tune | Wheel zoom | Right-drag pan"+legend,
                              wraplength=max(180,self.winfo_width()-6))
        for group,lane in enumerate(self.lanes):
            if group in self.visible_groups() and self.winfo_ismapped():
                lane._redraw()
            else:
                lane._sync_value()
        self._schedule_measure()

    def cancel_edits(self):
        self.state.cancel()
        for lane in getattr(self,"lanes",()):
            lane._editing_value,lane._value_origin=False,None
            lane._value_error=""
            lane._drag_bounds=lane._drag_press_y=lane._preview=lane._drag_value=None

    def settle_numeric(self):
        for lane in self.lanes:
            if lane._editing_value:
                lane._apply_value()
                if lane._editing_value:
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
