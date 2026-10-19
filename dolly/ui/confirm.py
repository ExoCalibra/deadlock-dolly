"""Dolly-styled modal confirmations for desktop workflows."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import ui_theme


def ask_reconstructed_helper(parent, *, size_mb: float) -> bool:
    """Ask once before the automatic reconstructed-audio helper download.

    This replaces the native Tk message box so the prompt uses Dolly's card
    palette, Segoe UI typography and teal primary action instead of system
    dialog colours.
    """
    tokens = ui_theme.TOKENS
    dialog = tk.Toplevel(parent)
    dialog.title("Reconstructed audio helper")
    dialog.configure(bg=tokens["bg"])
    dialog.resizable(False, False)
    dialog.transient(parent)
    result = {"value": False}

    def finish(value: bool) -> None:
        if not dialog.winfo_exists():
            return
        result["value"] = bool(value)
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()

    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    scale = max(1.0, float(parent.tk.call("tk", "scaling")) / (96 / 72))
    wrap = round(440 * scale)
    body = ttk.Frame(dialog, padding=round(18 * scale))
    body.pack(fill="both", expand=True)
    card = ttk.Frame(body, style="Card.TFrame", padding=round(18 * scale))
    card.pack(fill="both", expand=True)
    card.columnconfigure(0, weight=1)
    ttk.Label(card, text="RECONSTRUCTED AUDIO", style="Section.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Label(card, text="One-time helper download", style="CardTitle.TLabel").grid(
        row=1, column=0, sticky="w", pady=(6, 10))
    ttk.Label(
        card,
        text=(
            f"Reconstructed audio needs a one-time download of about {size_mb:.0f} MB "
            "from ValveResourceFormat. Dolly verifies the archive and the helper "
            "with SHA-256 before using them."
        ),
        style="Card.TLabel", wraplength=wrap, justify="left").grid(
            row=2, column=0, sticky="w")
    ttk.Label(
        card,
        text=(
            "The helper is cached for later exports. No account or manual setup is "
            "needed, and game-only audio works without it."
        ),
        style="CardMuted.TLabel", wraplength=wrap, justify="left").grid(
            row=3, column=0, sticky="w", pady=(10, 0))
    actions = ttk.Frame(card, style="Card.TFrame")
    actions.grid(row=4, column=0, sticky="e", pady=(18, 0))
    ttk.Button(actions, text="Not now", style="Card.TButton",
               command=lambda: finish(False)).pack(side="left")
    download = ttk.Button(actions, text="Download helper", style="Card.Primary.TButton",
                          command=lambda: finish(True))
    download.pack(side="left", padx=(8, 0))
    dialog.bind("<Escape>", lambda _event: finish(False))
    dialog.bind("<Return>", lambda _event: finish(True))
    dialog.update_idletasks()
    width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    try:
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        download.focus_set()
    except tk.TclError:
        pass
    dialog.wait_window()
    return result["value"]
