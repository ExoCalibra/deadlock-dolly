"""Library page view: explicit variables/actions, with locally owned widgets."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .widgets import GAP, ScrollPage, actions, card, disclosure, field


@dataclass(frozen=True)
class LibraryState:
    camera_driver: tk.Variable
    demo_path: tk.Variable
    game_path: tk.Variable
    hotkey_enabled: tk.Variable
    hotkey_label: tk.Variable
    path_summary: tk.Variable
    project_text: tk.Variable
    replay_search: tk.Variable
    startup_progress: tk.Variable


@dataclass(frozen=True)
class LibraryActions:
    browse_demo: Callable[..., object]
    browse_game: Callable[..., object]
    cancel_startup: Callable[..., object]
    filter_replays: Callable[..., object]
    refresh_replays: Callable[..., object]
    select_replay: Callable[..., object]
    start_editing_session: Callable[..., object]
    toggle_capture_hotkey: Callable[..., object]
    tree: Callable[..., object]
    use_selected_replay: Callable[..., object]
    new: Callable[..., object]
    open: Callable[..., object]
    rename: Callable[..., object]
    save: Callable[..., object]
    stop_session: Callable[..., object]
    save_as: Callable[..., object]


class LibraryPage:
    def __init__(self, parent, state: LibraryState, commands: LibraryActions):
        page = ScrollPage(parent)
        page.pack(fill="both", expand=True)
        self.library_page = page
        body = page.body
        ttk.Label(body, text="REPLAYS & SHOTS", style="Section.TLabel").pack(anchor="w", pady=(0, GAP))
        pair = ttk.Frame(body)
        pair.pack(fill="both", expand=True, pady=(0, GAP))
        for col in (0, 1):
            pair.columnconfigure(col, weight=1, uniform="library")
        left = ttk.Frame(pair, style="Rounded.Card.TFrame", padding=14)
        right = ttk.Frame(pair, style="Rounded.Card.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        for frame, title in ((left, "Replay library"), (right, "Selected replay")):
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(2, weight=1)
            ttk.Label(frame, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, GAP))
        search = ttk.Frame(left, style="Card.TFrame")
        search.grid(row=1, column=0, sticky="ew", pady=(0, GAP))
        field(search, "Find replay", state.replay_search)
        state.replay_search.trace_add("write", lambda *_: commands.filter_replays())
        table, self.replay_tree = commands.tree(left, ("name", "size", "modified"),
                                          ("Replay", "Size", "Modified"), (220, 75, 100), height=3)
        table.grid(row=2, column=0, sticky="nsew", pady=(0, GAP))
        self.replay_tree.column("name", anchor="w", minwidth=100)
        self.replay_tree.column("size", minwidth=50)
        self.replay_tree.column("modified", minwidth=70)
        self.replay_tree.bind("<<TreeviewSelect>>", commands.select_replay)
        self.replay_tree.bind("<Double-1>", lambda _e: commands.use_selected_replay())
        buttons = ttk.Frame(left, style="Card.TFrame")
        buttons.grid(row=3, column=0, sticky="ew")
        actions(buttons, (("Browse .dem...", commands.browse_demo), ("Refresh", commands.refresh_replays)), 2)
        self.selected_replay_text = tk.StringVar()
        selected = ttk.Frame(right, style="Card.TFrame")
        selected.grid(row=1, column=0, sticky="ew", pady=(0, GAP))
        ttk.Label(selected, text="Replay file", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 6))
        filename = ttk.Label(selected, textvariable=self.selected_replay_text, style="Card.TLabel", padding=(0, 7))
        filename.pack(fill="x", pady=(0, GAP))
        def update_name(*_):
            self.selected_replay_text.set(Path(state.demo_path.get()).name if state.demo_path.get() else "Choose a replay")
        state.demo_path.trace_add("write", update_name)
        update_name()
        info = ttk.Frame(right, style="Card.TFrame")
        info.grid(row=2, column=0, sticky="new", pady=(0, GAP))
        label = ttk.Label(info, text="Open in the paused in-game camera editor.", style="CardMuted.TLabel", wraplength=320)
        label.pack(anchor="w", pady=(0, GAP))
        right.bind("<Configure>", lambda e: (filename.configure(wraplength=max(180, e.width-36)), label.configure(wraplength=max(180, e.width-36))))
        launch = disclosure(info, "Launch setup")
        field(launch.body, "Deadlock executable", state.game_path)
        actions(launch.body, (("Browse game...", commands.browse_game),), 1)
        self.home_camera_driver_combo = field(launch.body, "Camera driver", state.camera_driver,
                                            values=("Native (experimental)", "Console (legacy)"))
        launch_row = ttk.Frame(right, style="Card.TFrame")
        launch_row.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.play_replay_button = ttk.Button(launch_row, text="Open replay in Dolly", style="Card.Primary.TButton", command=commands.start_editing_session)
        self.play_replay_button.pack(side="left")
        self.library_capture_toggle = ttk.Checkbutton(
            launch_row, textvariable=state.hotkey_label, variable=state.hotkey_enabled,
            command=commands.toggle_capture_hotkey)
        self.library_capture_toggle.pack(side="left", padx=(14, 0))
        ttk.Label(right, text="In-game camera capture follows this switch; set the shortcut in Controls.",
                  style="CardMuted.TLabel", wraplength=320).grid(row=4, column=0, sticky="w", pady=(0, 10))
        progress = card(body, "Session")
        self.startup_label = ttk.Label(progress, textvariable=state.startup_progress, style="CardMuted.TLabel", wraplength=780)
        self.startup_label.pack(fill="x", pady=(0, GAP))
        self.startup_bar = ttk.Progressbar(progress, mode="indeterminate")
        self.startup_bar.pack(fill="x", pady=(0, GAP))
        self.cancel_startup_button = actions(progress, (("Cancel startup", commands.cancel_startup),
            ("Stop / restore", commands.stop_session)), 2)[0]
        self.cancel_startup_button.configure(state="disabled")
        shot = card(body, "Shot files")
        ttk.Label(shot, textvariable=state.project_text, style="Card.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(shot, textvariable=state.path_summary, style="CardMuted.TLabel").pack(anchor="w", pady=(0, GAP))
        shot.pack_configure(before=progress)
        actions(shot, (("New shot", commands.new), ("Open shot...", commands.open), ("Save", commands.save),
                       ("Save as...", commands.save_as), ("Rename shot...", commands.rename)))
        ttk.Label(body, text="F8 panel - Frame cameras, edit the lens, and record inside Deadlock.", style="Muted.TLabel").pack(anchor="w")
