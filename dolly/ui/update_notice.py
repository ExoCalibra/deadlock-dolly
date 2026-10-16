"""A global update notice anchored below the desktop header."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import time

from .. import ui_theme
from .widgets import ScrollPage


class UpdateNotice:
    ANIMATION_SECONDS = 0.18
    FRAME_MS = 15
    MAX_NOTES_HEIGHT = 168

    def __init__(self, parent, *, update, notes, full_notes, later, reopen, height_limit=None):
        self.height_limit = height_limit
        self.scale = max(1.0, float(parent.tk.call("tk", "scaling")) / (96 / 72))
        style = ttk.Style(parent)
        style.configure("UpdateNotice.Border.TFrame", background=ui_theme.TOKENS["accent"])
        style.configure("UpdateNotice.Body.TFrame", background=ui_theme.TOKENS["selected"])
        # The theme supplies rounded corners on this selected-colour surface.
        # Copying the page card layout would replace them with page-colour corners.
        style.configure("UpdateNotice.Notes.TFrame", background=ui_theme.TOKENS["selected"])
        style.configure("UpdateNotice.Title.TLabel", background=ui_theme.TOKENS["selected"],
                        foreground=ui_theme.TOKENS["strong"],
                        font=(ui_theme.FONT_FAMILY, ui_theme.FONT_SIZES["card_title"], "bold"))
        style.configure("UpdateNotice.Detail.TLabel", background=ui_theme.TOKENS["selected"],
                        foreground=ui_theme.TOKENS["text"])
        for name in ("UpdateNotice.TButton", "UpdateNotice.Primary.TButton"):
            style.configure(name, background=ui_theme.TOKENS["selected"])
            style.map(name, background=[("active", ui_theme.TOKENS["selected"]),
                                        ("disabled", ui_theme.TOKENS["selected"])])
        self.frame = ttk.Frame(parent, style="UpdateNotice.Border.TFrame", padding=max(2, round(2 * self.scale)))
        self.body = ttk.Frame(self.frame, style="UpdateNotice.Body.TFrame", padding=(14, 10))
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.title = tk.StringVar(master=parent)
        self.detail = tk.StringVar(master=parent)
        self.title_label = ttk.Label(self.body, textvariable=self.title,
                                     style="UpdateNotice.Title.TLabel", wraplength=400)
        self.title_label.grid(row=0, column=0, sticky="w")
        self.detail_label = ttk.Label(self.body, textvariable=self.detail,
                                      style="UpdateNotice.Detail.TLabel", wraplength=400)
        self.detail_label.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.actions = ttk.Frame(self.body, style="UpdateNotice.Body.TFrame")
        self.actions.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))
        self.update_button = ttk.Button(self.actions, text="Update now", style="UpdateNotice.Primary.TButton", command=update)
        self.update_button.pack(side="left")
        self.notes_button = ttk.Button(self.actions, text="What's changed", width=14,
                                       style="UpdateNotice.TButton", command=notes)
        self.notes_button.pack(side="left", padx=(8, 0))
        self.later_button = ttk.Button(self.actions, text="Later", style="UpdateNotice.TButton", command=later)
        self.later_button.pack(side="left", padx=(8, 0))
        self.reminder = ttk.Button(parent, text="Update available", command=reopen)
        self.notes_open = False
        self._notes_release = None
        self._notes_content = None
        self._notes_height = 0
        self._animation_job = None
        self._animation_generation = 0
        self._fit_pending = False
        self._destroyed_flag = False
        self._notes_inset_y = round(12 * self.scale)
        self.notes_clip = ttk.Frame(self.body, style="UpdateNotice.Notes.TFrame", height=1,
                                    padding=(round(16 * self.scale), self._notes_inset_y))
        self.notes_clip.grid_propagate(False)
        self.notes_clip.columnconfigure(0, weight=1)
        self.notes_clip.rowconfigure(1, weight=1)
        notes_heading = ttk.Frame(self.notes_clip, style="Card.TFrame")
        notes_heading.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        notes_heading.columnconfigure(0, weight=1)
        ttk.Label(notes_heading, text="RELEASE HIGHLIGHTS", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.full_notes_button = ttk.Button(notes_heading, text="Full release notes", style="Quiet.TButton", command=full_notes)
        self.full_notes_button.grid(row=0, column=1, sticky="e")
        self.notes_heading = notes_heading
        self.notes_page = ScrollPage(self.notes_clip)
        self.notes_page.grid(row=1, column=0, sticky="nsew")
        self.notes_page.canvas.configure(background=ui_theme.TOKENS["panel"])
        self.notes_page.body.configure(style="Card.TFrame", padding=0)
        for column in (0, 1):
            self.notes_page.body.columnconfigure(column, weight=1, uniform="notes")
        self._note_labels = []
        self.notes_page.canvas.bind("<Configure>", self._notes_wrap, add="+")
        self.frame.bind("<Configure>", self._wrap)
        self.frame.bind("<Destroy>", self._destroyed, add="+")

    def set_notes(self, notes, *, release):
        content = tuple((item["title"], item["before"], item["after"]) for item in notes)
        if release == self._notes_release and content == self._notes_content:
            return
        if release != self._notes_release:
            self.close_notes()
        self._notes_release, self._notes_content = release, content
        for child in self.notes_page.body.winfo_children():
            child.destroy()
        self._note_labels = []
        if not content:
            ttk.Label(self.notes_page.body, text="Short notes aren't available for this release. You can still read the full release notes.",
                      style="CardMuted.TLabel", wraplength=650).grid(row=0, column=0, columnspan=2, sticky="w", pady=(8, 8))
        for index, (title, before, after) in enumerate(content):
            card = ttk.Frame(self.notes_page.body, style="Card.TFrame", padding=(0, 2, 14, 10))
            card.grid(row=index // 2, column=index % 2, sticky="new", padx=(0, 10))
            card.columnconfigure(0, weight=1)
            for row, (text, style) in enumerate(((title, "CardTitle.TLabel"),
                    ("Before: " + before, "CardMuted.TLabel"), ("After: " + after, "Card.TLabel"))):
                label = ttk.Label(card, text=text, style=style, wraplength=390, justify="left")
                label.grid(row=row, column=0, sticky="w", pady=(0, 5 if row < 2 else 0))
                self._note_labels.append(label)
        self.notes_page.canvas.yview_moveto(0)
        if self.notes_open:
            self.frame.update_idletasks()
            self._animate_to(self._target_height())

    def _notes_wrap(self, event):
        width = max(120, event.width // 2 - 30)
        for label in self._note_labels:
            if int(float(label.cget("wraplength"))) != width:
                label.configure(wraplength=width)

    def _target_height(self):
        requested = (self.notes_heading.winfo_reqheight() + self.notes_page.body.winfo_reqheight()
                     + 2 * self._notes_inset_y + 8)
        limit = round(self.MAX_NOTES_HEIGHT * self.scale)
        if self.height_limit is not None:
            limit = min(limit, max(1, int(self.height_limit())))
        return min(limit, max(1, requested))

    def fit_height(self):
        """Keep the open pane within its layout budget after a window resize."""
        if not self.notes_open or self._destroyed_flag:
            return
        if self._animation_job is not None:
            self._fit_pending = True
            return
        target = self._target_height()
        if target != self._notes_height:
            self._animate_to(target)

    def _cancel_animation(self):
        self._animation_generation += 1
        if self._animation_job is not None:
            try:
                self.frame.after_cancel(self._animation_job)
            except tk.TclError:
                pass
            self._animation_job = None

    def _animate_to(self, target):
        self._cancel_animation()
        generation = self._animation_generation
        start = self._notes_height
        started = time.monotonic()

        def tick():
            if self._destroyed_flag or generation != self._animation_generation:
                return
            progress = min(1.0, max(0.0, (time.monotonic() - started) / self.ANIMATION_SECONDS))
            eased = 1 - (1 - progress) ** 3
            self._notes_height = round(start + (target - start) * eased)
            self.notes_clip.configure(height=max(1, self._notes_height))
            if progress < 1:
                self._animation_job = self.frame.after(self.FRAME_MS, tick)
            else:
                self._animation_job = None
                if target == 0:
                    self.notes_clip.grid_remove()
                if self._fit_pending:
                    self._fit_pending = False
                    self.fit_height()
        tick()

    def toggle_notes(self):
        if self._destroyed_flag:
            return
        self.notes_open = not self.notes_open
        self.notes_button.configure(text="Hide changes" if self.notes_open else "What's changed")
        if self.notes_open:
            self.notes_clip.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
            self.frame.update_idletasks()
        self._animate_to(self._target_height() if self.notes_open else 0)

    def close_notes(self):
        self._cancel_animation()
        self.notes_open = False
        self._notes_height = 0
        self._fit_pending = False
        self.notes_clip.configure(height=1)
        self.notes_clip.grid_remove()
        self.notes_button.configure(text="What's changed")

    def _destroyed(self, event):
        if event.widget is self.frame:
            self._destroyed_flag = True
            self._cancel_animation()

    def _wrap(self, event):
        width = max(160, event.width - self.actions.winfo_reqwidth() - 48)
        self.title_label.configure(wraplength=width)
        self.detail_label.configure(wraplength=width)

    def show(self, version, detail, *, busy=False):
        self.title.set(f"Dolly {version} is available")
        self.detail.set(detail)
        self.update_button.configure(text="Downloading..." if busy else "Update now",
                                     state="disabled" if busy else "normal")
        self.reminder.grid_remove()
        self.frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))

    def collapse(self, version):
        self.close_notes()
        self.frame.grid_remove()
        self.reminder.configure(text=f"Update available · {version}")
        self.reminder.grid(row=2, column=0, columnspan=3, sticky="e", pady=(8, 0))

    def hide(self):
        self.close_notes()
        self.frame.grid_remove()
        self.reminder.grid_remove()
