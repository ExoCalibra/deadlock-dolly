"""Settings controls for the local Dolly-only graphics library."""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import graphics_profiles as profiles


class GraphicsProfiles:
    def __init__(self, parent, *, root, on_error):
        from .ui.widgets import actions, field
        self.root = root
        self.on_error = on_error
        self.library = None
        self.selection = tk.StringVar(value=profiles.CURRENT)
        self.status = tk.StringVar()
        self.combo = field(parent, "Next replay session", self.selection, values=(profiles.CURRENT,))
        self.combo.bind("<<ComboboxSelected>>", lambda _event: self.run(self.select))
        actions(parent, (("Save normal-play graphics...", lambda: self.run(self.capture)),
                         ("Import video.txt...", lambda: self.run(self.import_file)),
                         ("Preview changes...", lambda: self.run(self.preview))))
        actions(parent, (("Rename...", lambda: self.run(self.rename)),
                         ("Delete...", lambda: self.run(self.delete))), 2)
        ttk.Label(parent, text="Dolly uses clean settings in a separate folder for each replay session. Your normal-play configs stay untouched. "
                  "Saved profiles change only Dolly's quality settings. Display mode, resolution and GPU identity are kept; upscaling and render scale start clean. "
                  "Use Display launch options for window size.", wraplength=700, style="CardMuted.TLabel").pack(fill="x")
        ttk.Label(parent, textvariable=self.status, wraplength=700, style="CardMuted.TLabel").pack(fill="x", pady=(8, 0))
        try:
            self.refresh()
        except (OSError, ValueError, profiles.LaunchError) as exc:
            # Settings is built before the main log widget. Show the error
            # after construction so a damaged library cannot prevent startup.
            self.status.set(str(exc))
            self.root.after_idle(lambda error=exc: self.on_error("Graphics profiles", error))

    def run(self, action):
        try:
            action()
        except (OSError, ValueError, profiles.LaunchError) as exc:
            self.status.set(str(exc))
            self.on_error("Graphics profiles", exc)

    def refresh(self):
        self.library = profiles.load_library()
        self.combo.configure(values=(profiles.CURRENT, *(p["name"] for p in self.library["profiles"])))
        selected = next((p for p in self.library["profiles"] if p["id"] == self.library["selected"]), None)
        self.selection.set(selected["name"] if selected else profiles.CURRENT)
        self.status.set(f"{len(self.library['profiles'])} local profile(s). Selection applies to the next launch.")

    def selected_id(self):
        # Re-read disk so a removed/damaged library cannot silently become a
        # different launch choice. The launcher snapshots its values separately.
        library = profiles.load_library()
        name = self.selection.get()
        if name == profiles.CURRENT:
            return ""
        selected = next((p for p in library["profiles"] if p["name"] == name), None)
        if selected is None:
            raise profiles.LaunchError("Graphics profile changed outside this window. Reopen Settings and choose a profile.")
        return selected["id"]

    def select(self):
        selected = self.selected_id()
        library = profiles.load_library()
        library["selected"] = selected
        profiles.save_library(library)
        self.refresh()

    def chosen(self):
        selected = self.selected_id()
        library = profiles.load_library()
        profile = next((p for p in library["profiles"] if p["id"] == selected), None)
        if profile is None:
            raise ValueError("Select a named graphics profile first.")
        return library, profile

    def capture(self):
        self.add(profiles.capture_source())

    def import_file(self):
        name = filedialog.askopenfilename(parent=self.root, title="Import graphics from video.txt",
                                         filetypes=(("Video settings", "*.txt"),))
        if name:
            self.add(Path(name))

    def add(self, path):
        data = profiles.read_video(path)
        name = simpledialog.askstring("Save graphics profile", "Profile name (for example, Recording):", parent=self.root)
        if name is None:
            return
        profile = profiles.profile_from_bytes(name.strip(), data)
        kept = "\n".join(f"{profiles.QUALITY_FIELDS[k]}: {v}" for k, v in profile["values"].items())
        excluded = profiles.excluded_fields(data, profile)
        text = f"Source: {path}\n\nQuality values to save:\n{kept}\n\nExcluded fields (kept from the destination):\n" + "\n".join(excluded)
        def save():
            library = profiles.load_library()
            library["profiles"].append(profile)
            library["selected"] = profile["id"]
            profiles.save_library(library)
            self.refresh()
        self.show_preview("Save graphics profile", text, save)

    def preview(self):
        _library, profile = self.chosen()
        from .editing_session import preview_video
        _data, audit = preview_video(profile['id'])
        text = f"Separate Dolly session settings\nProfile: {profile['name']}\n\n"
        text += '\n'.join(f"{profiles.QUALITY_FIELDS[key]}: {value}" for key, value in audit['quality_values'].items())
        text += "\n\nNo game files are changed by this preview. Your normal-play settings and startup scripts are not imported. "
        text += "Only these reviewed quality values and display/device fields are written to Dolly's new session folder."
        self.show_preview("Next-launch graphics preview", text)

    def show_preview(self, title, text, save=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.geometry("740x540")
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        view = tk.Text(body, wrap="word", width=70, height=22)
        scroll = ttk.Scrollbar(body, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        view.pack(fill="both", expand=True)
        view.insert("1.0", text)
        view.configure(state="disabled")
        buttons = ttk.Frame(dialog, padding=12)
        buttons.pack(fill="x")
        if save is not None:
            def commit():
                save()
                dialog.destroy()
            ttk.Button(buttons, text="Save profile for next launch", command=lambda: self.run(commit)).pack(side="right")
        ttk.Button(buttons, text="Cancel" if save else "Close", command=dialog.destroy).pack(side="left")

    def rename(self):
        library, profile = self.chosen()
        name = simpledialog.askstring("Rename graphics profile", "New name:", initialvalue=profile["name"], parent=self.root)
        if name is not None:
            profile["name"] = name.strip()
            profiles.save_library(library)
            self.refresh()

    def delete(self):
        library, profile = self.chosen()
        if messagebox.askyesno("Delete graphics profile", f"Delete '{profile['name']}' from Dolly's local library?", parent=self.root):
            library["profiles"].remove(profile)
            library["selected"] = ""
            profiles.save_library(library)
            self.refresh()


def launch_options(app):
    panel = getattr(app, "graphics_profiles", None)
    selected = panel.selected_id() if panel is not None else ""
    return {"graphics_profile": selected} if selected else {}
