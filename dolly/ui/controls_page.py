"""One searchable home for desktop and in-game control preferences."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
import tkinter as tk
from tkinter import ttk

from .settings_page import CameraFeel
from .widgets import GAP, ScrollPage, card


@dataclass(frozen=True)
class ControlsActions:
    change_binding: Callable[[str], object]
    clear_binding: Callable[[str], object]
    reset_binding: Callable[[str], object]
    reset_all: Callable[[], object]
    save_movement: Callable[[], object]
    save_sensitivity: Callable[[], object]


class ControlsPage:
    def __init__(self, parent, records: Sequence[tuple[str, str, str]], commands: ControlsActions,
                 *, movement_speed, mouse_sensitivity, feedback):
        self.page = ScrollPage(parent)
        self.page.pack(fill="both", expand=True)
        body = self.page.body
        self.records = tuple(records)
        self.commands = commands
        self.rows, self.groups, self.binding_buttons = {}, {}, {}
        self._bindings = {}
        self._filter_after = None
        self._filter_query = None
        self._filter_to_top = False
        self.page.bind("<Destroy>", self._destroyed, add="+")
        ttk.Label(body, text="CONTROLS", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(body, text="Click a shortcut and press its replacement. Changes are saved across launches.",
                  style="Muted.TLabel", wraplength=620).pack(anchor="w", pady=(0, GAP))
        toolbar = ttk.Frame(body)
        toolbar.pack(fill="x", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, text="Find an action or shortcut", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.search = tk.StringVar(parent)
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search)
        self.search_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=(0, 12))
        self.reset_all_button = ttk.Button(toolbar, text="Reset all shortcuts", command=commands.reset_all,
                                          style="Quiet.TButton")
        self.reset_all_button.grid(row=1, column=1, sticky="e", pady=(5, 0))
        ttk.Label(body, textvariable=feedback, style="Muted.TLabel", wraplength=620).pack(fill="x", pady=(0, GAP))
        self.list_body = ttk.Frame(body)
        self.list_body.pack(fill="x")
        for action, label, group in self.records:
            if group not in self.groups:
                group_body = card(self.list_body, group)
                group_body.columnconfigure(0, weight=1)
                self.groups[group] = group_body
            group_body = self.groups[group]
            row = ttk.Frame(group_body, style="Card.TFrame")
            row.columnconfigure(0, weight=1)
            row.pack(fill="x", pady=(0, 7))
            ttk.Label(row, text=label, style="Card.TLabel", wraplength=220).grid(row=0, column=0, sticky="w", padx=(0, 12))
            shortcut = ttk.Button(row, width=20, command=lambda name=action: commands.change_binding(name),
                                  style="Card.Quiet.TButton")
            shortcut.grid(row=0, column=1, sticky="ew", padx=(0, 8))
            clear = ttk.Button(row, text="Clear", width=6, command=lambda name=action: commands.clear_binding(name),
                               style="Card.Quiet.TButton")
            clear.grid(row=0, column=2, padx=(0, 6))
            reset = ttk.Button(row, text="Reset", width=6, command=lambda name=action: commands.reset_binding(name),
                               style="Card.Quiet.TButton")
            reset.grid(row=0, column=3)
            self.rows[action] = row
            self.binding_buttons[action] = shortcut
            row.clear_button, row.reset_button = clear, reset
        self.empty_label = ttk.Label(self.list_body, text="No matching controls.", style="Muted.TLabel")
        ttk.Label(body, text="F7 is reserved for the game console and releases camera input. "
                  "Mouse 4 and Mouse 5 are the usual side buttons.", style="Muted.TLabel",
                  wraplength=620).pack(anchor="w", pady=(0, GAP))
        self.camera_feel = CameraFeel(body, mouse_sensitivity, commands.save_sensitivity)
        motion = card(body, "Camera movement")
        ttk.Label(motion, text="Move speed", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 6))
        fields = ttk.Frame(motion, style="Card.TFrame")
        fields.pack(fill="x")
        ttk.Entry(fields, textvariable=movement_speed, width=12, style="Card.TEntry").pack(side="left", padx=(0, 10))
        ttk.Button(fields, text="Save movement settings", command=commands.save_movement,
                   style="Card.Quiet.TButton").pack(side="left")
        self.search.trace_add("write", self._filter)
        def bind_focus(widget):
            if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton,
                                   ttk.Radiobutton, ttk.Scale, ttk.Menubutton, ttk.Spinbox)):
                widget.bind("<FocusIn>", self._focus_reveal, add="+")
            for child in widget.winfo_children():
                bind_focus(child)
        bind_focus(body)

    def _focus_reveal(self, event):
        self._reveal_if_needed(event.widget)

    def _reveal_if_needed(self, widget):
        canvas = self.page.canvas
        if not widget.winfo_ismapped() or not canvas.winfo_ismapped():
            return
        top, bottom = widget.winfo_rooty(), widget.winfo_rooty()+widget.winfo_height()
        visible_top = canvas.winfo_rooty()
        if top < visible_top or bottom > visible_top+canvas.winfo_height():
            self.page.reveal(widget)

    def refresh(self, bindings: Mapping[str, object]):
        self._bindings = dict(bindings)
        for action, button in self.binding_buttons.items():
            binding = bindings.get(action)
            button.configure(text=binding.label if binding else "Unbound")
            self.rows[action].clear_button.configure(state="normal" if binding else "disabled")
        self._filter()

    def _filter(self, *_args):
        query = self.search.get().strip().casefold()
        if query != self._filter_query:
            self._filter_query = query
            self._filter_to_top = True
        shown = set()
        for action, label, group in self.records:
            binding = self._bindings.get(action)
            text = " ".join((label, group, binding.label if binding else "Unbound")).casefold()
            row = self.rows[action]
            row.pack_forget()
            if not query or query in text:
                row.pack(fill="x", pady=(0, 7))
                shown.add(group)
        for group, group_body in self.groups.items():
            group_body.pack_forget()
            if group in shown:
                group_body.pack(fill="x", pady=(0, GAP))
        self.empty_label.pack_forget()
        if not shown:
            self.empty_label.pack(anchor="w", pady=(0, GAP))
        if self._filter_after is None:
            self._filter_after = self.page.after_idle(self._refresh_filter_geometry)

    def _refresh_filter_geometry(self):
        self._filter_after = None
        # An offscreen Canvas window can shrink without a body Configure
        # event. Finish its queued geometry, then refresh the scroll bounds.
        self.page.update_idletasks()
        if self.page.winfo_exists():
            self.page._resize()
            if self._filter_to_top:
                # A new search starts with its first result in view. Updating
                # existing shortcut labels keeps the user's scroll position.
                self._filter_to_top = False
                self.page.canvas.yview_moveto(0)

    def _destroyed(self, event):
        if event.widget is self.page and self._filter_after is not None:
            self.page.after_cancel(self._filter_after)
            self._filter_after = None

    def reveal_action(self, action):
        self.search.set("")
        self.page.update_idletasks()
        self._reveal_if_needed(self.binding_buttons[action])
        self.binding_buttons[action].focus_set()
