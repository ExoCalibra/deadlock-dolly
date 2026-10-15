"""Settings page view: explicit variables/actions, with locally owned widgets."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import tkinter as tk
from tkinter import ttk

from .widgets import GAP, ScrollPage, actions, card, disclosure, field


SENSITIVITY_MIN = 0.005
SENSITIVITY_MAX = 2.0
SENSITIVITY_TICKS = 1000
SENSITIVITY_PRESETS = (
    ("Very slow", 0.02),
    ("Slow", 0.05),
    ("Normal", 0.12),
    ("Fast", 0.25),
    ("Very fast", 0.5),
)


def sensitivity_to_position(value: float) -> float:
    bounded = min(max(float(value), SENSITIVITY_MIN), SENSITIVITY_MAX)
    position = SENSITIVITY_TICKS * math.log(bounded / SENSITIVITY_MIN) / math.log(SENSITIVITY_MAX / SENSITIVITY_MIN)
    return min(max(position, 0.0), float(SENSITIVITY_TICKS))


def position_to_sensitivity(position: float) -> float:
    bounded = min(max(float(position), 0.0), float(SENSITIVITY_TICKS))
    return SENSITIVITY_MIN * (SENSITIVITY_MAX / SENSITIVITY_MIN) ** (bounded / SENSITIVITY_TICKS)


def sensitivity_preset_name(value: float) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "Custom"
    if not math.isfinite(value) or value <= 0:
        return "Custom"
    label, preset = min(SENSITIVITY_PRESETS, key=lambda item: abs(math.log(value / item[1])))
    return label if abs(math.log(value / preset)) <= math.log(1.25) else "Custom"


@dataclass(frozen=True)
class SettingsState:
    game_path: tk.Variable
    replay_folder: tk.Variable
    reshade_runtime_path: tk.Variable
    reshade_status_text: tk.Variable
    show_log: tk.Variable
    auto_updates_initial: bool
    mouse_sensitivity: tk.Variable


@dataclass(frozen=True)
class SettingsActions:
    browse_game: Callable[..., object]
    browse_replay_folder: Callable[..., object]
    browse_reshade: Callable[..., object]
    browse_reshade_library: Callable[..., object]
    check_updates: Callable[..., object]
    configure_reshade: Callable[..., object]
    diagnostics: Callable[..., object]
    disable_reshade: Callable[..., object]
    forget_reshade: Callable[..., object]
    open_advanced_startup: Callable[..., object]
    open_launch_options: Callable[..., object]
    recover_game_config: Callable[..., object]
    save_layout_paths: Callable[..., object]
    save_mouse_sensitivity: Callable[..., object]
    save_update_preference: Callable[..., object]
    select_reshade_runtime: Callable[..., object]
    toggle_log: Callable[..., object]
    build_keybinds: Callable[..., object]
    show_reshade_keybinds: Callable[..., object]


class SettingsPage:
    def __init__(self, parent, state: SettingsState, commands: SettingsActions, *, root, on_error):
        page = ScrollPage(parent)
        page.pack(fill="both", expand=True)
        self.settings_page = page
        self.commands = commands
        body = page.body
        ttk.Label(body, text="SETTINGS", style="Section.TLabel").pack(anchor="w", pady=(0, GAP))
        updates = card(body, "Updates")
        self.auto_updates = tk.BooleanVar(value=state.auto_updates_initial)
        self.update_status = tk.StringVar(value="Checks published Latest releases; experimental pre-releases are ignored.")
        ttk.Checkbutton(updates, style="Card.TCheckbutton", text="Automatically check for updates", variable=self.auto_updates,
                        command=commands.save_update_preference).pack(anchor="w", pady=(0, GAP))
        ttk.Label(updates, text="Nothing downloads or installs until you choose Update now.",
                  wraplength=700, style="CardMuted.TLabel").pack(anchor="w", pady=(0, GAP))
        self.update_check_button = actions(updates, (("Check for updates", commands.check_updates),), 1)[0]
        ttk.Label(updates, textvariable=self.update_status, wraplength=700, style="CardMuted.TLabel").pack(fill="x")
        game = card(body, "Game & files")
        field(game, "Deadlock executable", state.game_path)
        actions(game, (("Browse game...", commands.browse_game),), 1)
        field(game, "Replay folder", state.replay_folder)
        actions(game, (("Browse folder...", commands.browse_replay_folder), ("Save paths", commands.save_layout_paths)), 2)
        actions(game, (("Display launch options...", commands.open_launch_options),), 1)
        self._build_camera_feel(body, state, commands)
        from ..graphics_profiles_ui import GraphicsProfiles
        self.graphics_profiles = GraphicsProfiles(card(body, "Replay graphics profiles"), root=root, on_error=on_error)
        self.controls_disclosure = disclosure(body, "Controls & keybinds")
        self.keybinds_tab = self.controls_disclosure.body
        commands.build_keybinds(self.keybinds_tab)
        self.reshade_card = shade = card(body, "ReShade")
        self.reshade_path_entry = field(shade, "Runtime DLL", state.reshade_runtime_path)
        self.reshade_path_entry.bind(
            "<Return>", lambda _event: commands.select_reshade_runtime(state.reshade_runtime_path.get()))
        self.reshade_browse_button, self.reshade_library_button = actions(
            shade, (("Browse runtime...", commands.browse_reshade),
                    ("Browse FX library...", commands.browse_reshade_library)), 2)
        buttons = actions(shade, (("Enable ReShade", commands.configure_reshade),
                        ("Disable for this session", commands.disable_reshade), ("Forget runtime", commands.forget_reshade)))
        self.reshade_configure_button, self.reshade_disable_button, self.reshade_forget_button = buttons
        self.reshade_disable_button.configure(state="disabled")
        actions(shade, (("Menu shortcut...", commands.show_reshade_keybinds),), 1)
        ttk.Label(shade, textvariable=state.reshade_status_text, style="CardMuted.TLabel", wraplength=760).pack(fill="x")
        tools = disclosure(body, "Troubleshooting & recovery")
        actions(tools.body, (("Startup controls...", commands.open_advanced_startup),
                             ("Recover configuration...", commands.recover_game_config),
                             ("Export diagnostics", commands.diagnostics)))
        ttk.Checkbutton(tools.body, text="Show log", variable=state.show_log, command=commands.toggle_log).pack(anchor="w", pady=(0, GAP))

    def _build_camera_feel(self, body, state, commands):
        self.mouse_sensitivity = state.mouse_sensitivity
        self._sensitivity_syncing = False
        self.sensitivity_position = tk.DoubleVar(value=sensitivity_to_position(self._sensitivity_value()))
        self.sensitivity_text = tk.StringVar()
        feel = card(body, "Camera feel")
        ttk.Label(feel, text="Free-camera look speed. Lower it when a high-DPI mouse makes the "
                             "camera spin, or raise it for a slow desktop mouse.",
                  style="CardMuted.TLabel", wraplength=760).pack(anchor="w", pady=(0, GAP))
        presets = ttk.Frame(feel, style="Card.TFrame")
        presets.pack(fill="x", pady=(0, GAP))
        for label, value in SENSITIVITY_PRESETS:
            ttk.Button(presets, text=label, style="Card.Quiet.TButton",
                       command=lambda preset=value: self._apply_sensitivity(preset)).pack(side="left", padx=(0, 8))
        slider = ttk.Scale(feel, from_=0, to=SENSITIVITY_TICKS, orient="horizontal",
                           variable=self.sensitivity_position, command=self._sensitivity_moved)
        slider.pack(fill="x")
        slider.bind("<ButtonRelease-1>", self._sensitivity_released)
        ttk.Label(feel, textvariable=self.sensitivity_text, style="CardMuted.TLabel").pack(anchor="w", pady=(6, 0))
        self.mouse_sensitivity.trace_add("write", self._sensitivity_state_changed)
        self._sensitivity_text_refresh(self._sensitivity_value())

    def _sensitivity_value(self):
        try:
            value = float(self.mouse_sensitivity.get())
        except (TypeError, ValueError):
            return SENSITIVITY_PRESETS[2][1]
        return value if math.isfinite(value) and value > 0 else SENSITIVITY_PRESETS[2][1]

    def _sensitivity_text_refresh(self, value):
        self.sensitivity_text.set(f"Current: {value:.3g} ({sensitivity_preset_name(value)})")

    def _sensitivity_moved(self, _position=None):
        self._sensitivity_text_refresh(position_to_sensitivity(self.sensitivity_position.get()))

    def _sensitivity_released(self, _event=None):
        self._apply_sensitivity(position_to_sensitivity(self.sensitivity_position.get()))

    def _apply_sensitivity(self, value):
        value = position_to_sensitivity(sensitivity_to_position(value))
        self._sensitivity_syncing = True
        try:
            self.sensitivity_position.set(sensitivity_to_position(value))
            self.mouse_sensitivity.set(f"{value:.4g}")
            self._sensitivity_text_refresh(value)
        finally:
            self._sensitivity_syncing = False
        self.commands.save_mouse_sensitivity()

    def _sensitivity_state_changed(self, *_args):
        if self._sensitivity_syncing:
            return
        value = self._sensitivity_value()
        self._sensitivity_syncing = True
        try:
            self.sensitivity_position.set(sensitivity_to_position(value))
            self._sensitivity_text_refresh(value)
        finally:
            self._sensitivity_syncing = False
