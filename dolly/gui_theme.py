"""Wireframe-style ttk surfaces, preserving the native widgets and bindings."""
import base64
import math
import struct
import tkinter as tk
from tkinter import ttk
import zlib

from . import ui_theme


def initialize(root):
    """Initialize Dolly's current desktop theme in its established order.

    Base ttk styles precede selection handling, rounded assets and wheel guards.
    Call once per Tk root, before constructing the desktop views.
    """
    _F = ui_theme.FONT_SIZES
    FAMILY = ui_theme.FONT_FAMILY
    BG = ui_theme.TOKENS["bg"]
    PANEL = ui_theme.TOKENS["panel"]
    PANEL_ALT = ui_theme.TOKENS["panel_alt"]
    FIELD = ui_theme.TOKENS["field"]
    EDGE = ui_theme.TOKENS["edge"]
    TEXT = ui_theme.TOKENS["text"]
    MUTED = ui_theme.TOKENS["muted"]
    ACCENT = ui_theme.TOKENS["accent"]
    ACCENT_HOVER = ui_theme.TOKENS["accent_hover"]
    ACCENT_INK = ui_theme.TOKENS["accent_ink"]
    BUTTON = ui_theme.TOKENS["button"]
    BUTTON_HOVER = ui_theme.TOKENS["button_hover"]
    DISABLED_BG = ui_theme.TOKENS["disabled_bg"]
    DISABLED_FG = ui_theme.TOKENS["disabled_fg"]
    SELECTED = ui_theme.TOKENS["selected"]
    SELECTED_INK = ui_theme.TOKENS["selected_ink"]
    TRACK = ui_theme.TOKENS["track"]
    WARN = ui_theme.TOKENS["warn"]
    WARN_BG = ui_theme.TOKENS["warn_bg"]
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=(FAMILY, _F["body"]))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Card.TLabel", background=PANEL)
    style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED)
    style.configure("Title.TLabel", font=(FAMILY, _F["title"], "bold"))
    style.configure("Section.TLabel", font=(FAMILY, _F["section"], "bold"), foreground=MUTED)
    style.configure("CardTitle.TLabel", background=PANEL, font=(FAMILY, _F["card_title"], "bold"))
    style.configure("Accent.TLabel", foreground=ACCENT)
    style.configure("Pill.TLabel", background=SELECTED, foreground=ACCENT,
                    font=(FAMILY, _F["small"], "bold"), padding=(9, 3))
    style.configure("PillConsole.TLabel", background=WARN_BG, foreground=WARN,
                    font=(FAMILY, _F["small"], "bold"), padding=(9, 3))
    style.configure("TButton", background=BUTTON, foreground=TEXT, padding=(10, 6), borderwidth=0)
    style.map("TButton", background=[("active", BUTTON_HOVER), ("disabled", DISABLED_BG)],
              foreground=[("disabled", DISABLED_FG)])
    style.configure("Primary.TButton", background=ACCENT, foreground=ACCENT_INK, font=(FAMILY, _F["body"], "bold"))
    style.map("Primary.TButton", background=[("active", ACCENT_HOVER), ("disabled", DISABLED_BG)],
              foreground=[("disabled", DISABLED_FG)])
    style.configure("Quiet.TButton", background=PANEL, padding=(8, 5))
    style.configure("TMenubutton", background=PANEL, foreground=MUTED,
                    arrowcolor=MUTED, padding=(5, 2), borderwidth=0)
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE, padding=5)
    style.configure("TCombobox", fieldbackground=FIELD, background=BUTTON, foreground=TEXT,
                    arrowcolor=MUTED, borderwidth=0, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
    style.configure("TCheckbutton", background=BG, foreground=MUTED, padding=0)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", TEXT)])
    style.configure("TNotebook", background=BG, borderwidth=0, bordercolor=BG, lightcolor=BG, darkcolor=BG, tabmargins=(0, 0, 0, 6))
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(17, 9), borderwidth=0, bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
    style.layout("TNotebook.Tab", [("Notebook.padding", {"sticky": "nswe", "children": [("Notebook.label", {"sticky": "nswe"})]})])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=31, borderwidth=0, lightcolor=PANEL, darkcolor=PANEL)
    style.configure("Treeview.Heading", background=PANEL_ALT, foreground=MUTED, bordercolor=PANEL_ALT, lightcolor=PANEL_ALT, darkcolor=PANEL_ALT, padding=(8, 7),
                    relief="flat", borderwidth=0, font=(FAMILY, _F["small"]))
    style.map("Treeview", background=[("selected", SELECTED)], foreground=[("selected", SELECTED_INK)])
    style.configure("Vertical.TScrollbar", background=EDGE, troughcolor=PANEL, arrowcolor=MUTED,
                    borderwidth=0, arrowsize=12, relief="flat")
    style.configure("Horizontal.TScale", background=BG, troughcolor=TRACK, sliderlength=16,
                    sliderthickness=14, borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=TRACK, bordercolor=PANEL,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=5, borderwidth=0)
    style.configure("TLabelframe", background=BG, bordercolor=EDGE)
    style.configure("TLabelframe.Label", foreground=MUTED)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.bind_class("TCombobox", "<<ComboboxSelected>>",
                         _clear_committed_combobox_selection, add="+")

    apply(root)
    install_wheel_guard(root)


def _clear_committed_combobox_selection(event):
    """Remove Tk's automatic text highlight after choosing a dropdown item.

    Leave focus, the insertion cursor, and ordinary typing/drag selection
    alone. Waiting for idle lets the platform's combobox binding finish.
    """
    widget = event.widget
    def clear():
        try:
            widget.selection_clear()
        except tk.TclError:
            pass  # The option's callback may have closed its dialog.
    widget.after_idle(clear)


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _photo(root, width, height, pixel, *, surface=None):
    """Small RGBA assets with smooth edges, generated without a runtime library."""
    raw = bytearray()
    backdrop = _rgb(surface) if surface is not None else None
    for y in range(height):
        raw.append(0)
        for x in range(width):
            color = pixel(x + .5, y + .5)
            if backdrop is not None:
                alpha = color[3]
                color = (*((value * alpha + parent * (255 - alpha) + 127) // 255
                           for value, parent in zip(color[:3], backdrop)), 255)
            raw.extend(color)
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return tk.PhotoImage(master=root, data=base64.b64encode(png), format="png")


def _coverage(distance):
    return max(0.0, min(1.0, .5 - distance))


def _segment_distance(x, y, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)


def rounded_image(root, fill, outline, radius=6, *, size=64, line=1, checked=None, surface=None):
    fill, outline = _rgb(fill), _rgb(outline)
    tick = _rgb(checked) if checked else None
    width, height = (size, size) if isinstance(size, int) else size
    def pixel(x, y):
        qx, qy = abs(x - width / 2) - (width / 2 - radius), abs(y - height / 2) - (height / 2 - radius)
        distance = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
        alpha = _coverage(distance)
        if not alpha:
            return 0, 0, 0, 0
        inside = _coverage(distance + line)
        color = tuple(round((a * inside + b * (alpha - inside)) / alpha) for a, b in zip(fill, outline))
        if tick:
            a, b, c = (size * .23, size * .5), (size * .43, size * .7), (size * .77, size * .3)
            ink = _coverage(min(_segment_distance(x, y, a, b), _segment_distance(x, y, b, c)) - size * .055)
            color = tuple(round(a * (1 - ink) + b * ink) for a, b in zip(color, tick))
        return *color, round(255 * alpha)
    return _photo(root, width, height, pixel, surface=surface)


def apply(root):
    style = ttk.Style(root)
    images = []
    scale = max(1, root.winfo_fpixels("1i") / 96)
    t = ui_theme.TOKENS
    bg, panel, text, muted, accent = t["bg"], t["panel"], t["text"], t["muted"], t["accent"]
    edge, field = t["edge"], t["field"]
    control_radius, card_radius = round(5 * scale), round(6 * scale)
    surfaces = {}
    minimum_images = {}
    def rounded(name, fill, outline, radius=control_radius, min_width=16, surface=bg, **states):
        paints = [(None, fill, outline), *((state, *colors) for state, colors in states.items())]
        if scale > 2:
            # Clam's field has two border pixels. Preserve the original precise
            # stroke above 200% until an equivalent native primitive is proven.
            variants = [rounded_image(root, color, edge, radius, line=scale, surface=surface)
                        for _, color, edge in paints]
            images.extend(variants)
            style.element_create(name, "image", variants[0],
                                 *((state, image) for (state, _, _), image in zip(paints[1:], variants[1:])),
                                 border=radius, padding=0, width=min_width, height=16, sticky="nsew")
            return
        # A native fill paints the large center once. Image elements only stamp
        # the four small antialiased corners; no nine-slice center is tiled.
        style.element_create(name, "from", "clam", "background")
        style.element_create(name + ".fill", "from", "clam", "field")
        minimum = minimum_images.get(min_width)
        if minimum is None:
            minimum = tk.PhotoImage(master=root, width=min_width, height=16)
            minimum_images[min_width] = minimum
            images.append(minimum)
        style.element_create(name + ".minimum", "image", minimum,
                             width=min_width, height=16, sticky="")
        corners = {key: [] for key in ("nw", "ne", "sw", "se")}
        for state, color, edge in paints:
            original = rounded_image(root, color, edge, radius, line=scale, surface=surface)
            width, height = original.width(), original.height()
            for key, (x, y) in {"nw": (0, 0), "ne": (width-radius, 0),
                                "sw": (0, height-radius), "se": (width-radius, height-radius)}.items():
                corner = tk.PhotoImage(master=root, width=radius, height=radius)
                root.tk.call(str(corner), "copy", str(original), "-from", x, y, x+radius, y+radius)
                images.append(corner)
                corners[key].append((state, corner))
        for key, variants in corners.items():
            style.element_create(name + "." + key, "image", variants[0][1],
                                 *((state, image) for state, image in variants[1:]),
                                 width=radius, height=radius, sticky=key)
        surfaces[name] = paints
    rounded("Dolly.card", panel, edge, card_radius)
    rounded("Dolly.card.notice", panel, edge, card_radius, surface=t["selected"])
    style.layout("Rounded.Card.TFrame", [("Dolly.card", {"sticky": "nsew"})])
    style.configure("Rounded.Card.TFrame", background=bg)
    style.layout("UpdateNotice.Notes.TFrame", [("Dolly.card.notice", {"sticky": "nsew"})])
    style.configure("UpdateNotice.Notes.TFrame", background=t["selected"])
    # Large image elements repaint often. Precompose their antialiased edges
    # onto the exact parent surface so Tk can use its opaque image path.
    # Card variants are separate: page-coloured corners would leave halos.
    for suffix, surface in (("", bg), (".card", panel), (".notice", t["selected"])):
        rounded("Dolly.button" + suffix, t["button"], t["button"], surface=surface,
                disabled=(t["disabled_bg"], t["edge"]), pressed=(t["button_active"], accent),
                focus=(t["button"], accent), active=(t["button_hover"], accent))
        rounded("Dolly.primary" + suffix, accent, accent, surface=surface,
                disabled=(t["disabled_bg"], t["edge"]), focus=(accent, t["selected_ink"]),
                pressed=(t["accent_active"], t["accent_active"]), active=(t["accent_hover"], t["accent_hover"]))
    def button_layout(element):
        return [(element, {"sticky": "nsew", "children": [("Button.padding", {
            "sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})]
    style.layout("TButton", button_layout("Dolly.button"))
    style.layout("Primary.TButton", button_layout("Dolly.primary"))
    style.layout("Card.TButton", button_layout("Dolly.button.card"))
    style.layout("Card.Quiet.TButton", button_layout("Dolly.button.card"))
    style.layout("Card.Primary.TButton", button_layout("Dolly.primary.card"))
    style.layout("UpdateNotice.TButton", button_layout("Dolly.button.notice"))
    style.layout("UpdateNotice.Primary.TButton", button_layout("Dolly.primary.notice"))
    style.configure("TButton", padding=(10, 5))
    style.configure("Quiet.TButton", padding=(10, 5))
    # Curve axes are local selectors: keep inactive channels quiet and give the
    # active channel the same filled, outlined state as the in-game editor.
    rounded("Dolly.curve.axis", panel, panel, surface=panel,
            disabled=(panel, panel), focus=(panel, accent), active=(t["button"], t["edge"]))
    rounded("Dolly.curve.axis.selected", t["selected"], t["selected_edge"], surface=panel,
            disabled=(t["disabled_bg"], t["edge"]), focus=(t["selected"], accent),
            active=(t["selected"], t["selected_edge"]))
    for name, element in (("Curve.Axis.TButton", "Dolly.curve.axis"),
                          ("Curve.Selected.Axis.TButton", "Dolly.curve.axis.selected")):
        style.layout(name, button_layout(element))
        style.configure(name, padding=(10, 3), background=panel,
                        foreground=t["selected_ink"] if "Selected" in name else text)
        style.map(name, background=[("active", panel), ("disabled", panel)],
                  foreground=[("disabled", t["disabled_fg"])])
    for name, surface in (("TButton", bg), ("Primary.TButton", bg), ("Quiet.TButton", bg),
                          ("Card.TButton", panel), ("Card.Primary.TButton", panel), ("Card.Quiet.TButton", panel)):
        style.configure(name, background=surface)
        style.map(name, background=[("active", surface), ("disabled", surface)])
    rounded("Dolly.nav", bg, bg, focus=(bg, accent), active=(panel, edge))
    rounded("Dolly.nav.selected", bg, accent, focus=(panel, accent))
    rounded("Dolly.nav.current", bg, bg, focus=(panel, panel), active=(panel, panel))
    style.layout("Nav.TButton", button_layout("Dolly.nav"))
    style.layout("Selected.Nav.TButton", button_layout("Dolly.nav.selected"))
    # The sidebar draws the selection outline. Focus on that selected button
    # adds a quiet fill, rather than a second outline inside the first.
    style.layout("Current.Nav.TButton", button_layout("Dolly.nav.current"))
    style.configure("Nav.TButton", anchor="w", padding=(12, 8), background=bg)
    style.configure("Selected.Nav.TButton", foreground=accent)
    style.configure("Current.Nav.TButton", foreground=accent)
    for name in ("Nav.TButton", "Selected.Nav.TButton", "Current.Nav.TButton"):
        style.map(name, background=[("active", bg)], foreground=[("active", accent)])
    for label, surface in (("Disclosure.TButton", bg), ("Disclosure.Card.TButton", panel)):
        style.layout(label, [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "w"})]})])
        style.configure(label, background=surface, foreground=text, padding=(0, 5), borderwidth=0)
        style.map(label, background=[("active", surface)], foreground=[("active", accent)])

    for suffix, surface in (("", bg), (".card", panel)):
        rounded("Dolly.field" + suffix, field, edge, surface=surface,
                disabled=(t["disabled_bg"], t["edge"]), focus=(field, accent), active=(field, t["accent_active"]))
    def entry_layout(element):
        return [(element, {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})]
    style.layout("TEntry", entry_layout("Dolly.field"))
    style.layout("Card.TEntry", entry_layout("Dolly.field.card"))
    style.layout("Numeric.TEntry", entry_layout("Dolly.field.card"))
    def arrow_pixel(x, y):
        ink = _coverage(min(_segment_distance(x, y, (3, 5), (7, 9)),
                            _segment_distance(x, y, (7, 9), (11, 5))) - .7)
        return *_rgb(muted), round(255 * ink)
    arrow = _photo(root, 14, 14, arrow_pixel)
    images.append(arrow)
    style.element_create("Dolly.Combobox.downarrow", "image", arrow, width=20, sticky="")
    def combo_layout(element):
        return [(element, {"sticky": "nsew", "children": [
            ("Combobox.padding", {"sticky": "nsew", "children": [
                ("Dolly.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                ("Combobox.textarea", {"sticky": "nsew"})]})]})]
    def menu_layout(element):
        return [(element, {"sticky": "nsew", "children": [
            ("Menubutton.padding", {"sticky": "nsew", "children": [
                ("Dolly.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                ("Menubutton.label", {"sticky": "nsew"})]})]})]
    for prefix, suffix, surface in (("", "", bg), ("Card.", ".card", panel)):
        style.layout(prefix + "TCombobox", combo_layout("Dolly.field" + suffix))
        rounded("Dolly.menu" + suffix, panel, edge, surface=surface, disabled=(t["disabled_bg"], edge),
                focus=(panel, accent), pressed=(t["button_active"], accent), active=(t["button_hover"], edge))
        style.layout(prefix + "TMenubutton", menu_layout("Dolly.menu" + suffix))
    # Image corners are transparent. The widget rectangle behind them must
    # stay on its parent surface even when clam marks a dropdown active or
    # readonly; its inherited pale background otherwise creates square boxes.
    for prefix, surface in (("", bg), ("Card.", panel)):
        for control in ("TEntry", "TCombobox", "TMenubutton"):
            style.configure(prefix + control, background=surface)
            style.map(prefix + control, background=[("disabled", surface), ("!disabled", surface)])
    style.configure("TMenubutton", borderwidth=0, relief="flat")
    style.map("TMenubutton", foreground=[("disabled", t["disabled_fg"])])
    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=field, background=bg, foreground=text,
                        borderwidth=0, padding=(10, 5))
        style.map(name, fieldbackground=[("disabled", t["disabled_bg"]), ("readonly", field)],
                  foreground=[("disabled", t["disabled_fg"]), ("readonly", text)])
        style.configure("Card." + name, background=panel)

    style.configure("Numeric.TEntry", padding=(4, 1), background=panel)
    style.map("Numeric.TEntry", background=[("disabled", panel), ("!disabled", panel)])

    size = round(14 * scale)
    indicator = rounded_image(root, field, edge, round(3 * scale), size=size, line=scale)
    checked = rounded_image(root, accent, accent, round(3 * scale), size=size, line=scale, checked=bg)
    hover = rounded_image(root, field, accent, round(3 * scale), size=size, line=scale)
    disabled = rounded_image(root, t["disabled_bg"], t["edge"], round(3 * scale), size=size, line=scale)
    disabled_checked = rounded_image(root, t["accent_active"], t["accent_active"], round(3 * scale), size=size, line=scale, checked=muted)
    images.extend((indicator, checked, hover, disabled, disabled_checked))
    focused_checked = rounded_image(root, accent, text, round(3 * scale), size=size, line=scale, checked=bg)
    images.append(focused_checked)
    style.element_create("Dolly.Checkbutton.indicator", "image", indicator,
                         ("disabled selected", disabled_checked), ("disabled", disabled),
                         ("focus selected", focused_checked), ("focus", hover),
                         ("selected", checked), ("active", hover), sticky="w", width=size + 8)
    style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [
        ("Dolly.Checkbutton.indicator", {"side": "left", "sticky": "w"}),
        ("Checkbutton.label", {"sticky": "nsew"})]})])
    style.configure("TCheckbutton", foreground=text)
    style.configure("Card.TCheckbutton", background=panel)
    style.map("Card.TCheckbutton", background=[("active", panel)])

    style.layout("FullEditor.TCheckbutton", [("Dolly.nav.selected", {"sticky": "nsew", "children":
        style.layout("TCheckbutton")})])
    style.configure("FullEditor.TCheckbutton", padding=(12, 9), background=bg)

    def match_surface(event):
        widget = event.widget
        # Tk creates combobox popdown scrollbars in Tcl rather than through
        # tkinter; those Map events carry a path, not a Python widget.
        if not isinstance(widget, ttk.Widget):
            return
        name = str(widget.cget("style")) or widget.winfo_class()
        if name in ("TScrollbar", "TScale"):
            name = ("Vertical" if str(widget.cget("orient")) == "vertical" else "Horizontal") + "." + name
        if name not in ("TEntry", "TCombobox", "TMenubutton", "TButton", "Primary.TButton", "Quiet.TButton", "TCheckbutton",
                        "Vertical.TScrollbar", "Horizontal.TScrollbar", "Vertical.TScale", "Horizontal.TScale"):
            return
        parent = widget.master
        while parent is not None:
            if isinstance(parent, ttk.Widget):
                parent_style = str(parent.cget("style")) or parent.winfo_class()
                if "Card." in parent_style or style.lookup(parent_style, "background") == panel:
                    widget.configure(style="Card." + name)
                    return
                if style.lookup(parent_style, "background") == bg:
                    return
            parent = getattr(parent, "master", None)
    for cls in ("TEntry", "TCombobox", "TMenubutton", "TButton", "TCheckbutton", "TScrollbar", "TScale"):
        root.bind_class(cls, "<Map>", match_surface, add="+")

    # Keep the native *thumb/*trough names: ttk uses them to distinguish
    # dragging from page clicks. Matching the trough to its parent avoids an
    # inset square rail, while opaque assets avoid repeated alpha blending.
    thickness, minimum = round(10 * scale), round(16 * scale)
    radius = max(1, round(4 * scale))
    for direction in ("Vertical", "Horizontal"):
        vertical = direction == "Vertical"
        # ttk tiles its image centers. Keep a long transparent strip along
        # the scrolling axis, with exactly the rail's cross-axis thickness;
        # a 1px tile is expensive and a square asset can widen the layout.
        strip_size = (thickness, 64) if vertical else (64, thickness)
        size = (thickness, max(64, minimum)) if vertical else (max(64, minimum), thickness)
        for prefix, surface in (("", bg), ("Card.", panel)):
            rail = _photo(root, *strip_size, lambda x, y: (0, 0, 0, 0), surface=surface)
            thumbs = [rounded_image(root, color, color, radius, size=size, line=0, surface=surface)
                      for color in (edge, t["scroll_hover"], accent, t["disabled_bg"])]
            images.extend((rail, *thumbs))
            trough = "Dolly." + prefix + direction + ".Scrollbar.trough"
            thumb = "Dolly." + prefix + direction + ".Scrollbar.thumb"
            style.element_create(trough, "image", rail, width=1, height=1, sticky="nsew")
            style.element_create(thumb, "image", thumbs[0], ("disabled", thumbs[3]),
                                 ("pressed", thumbs[2]), ("active", thumbs[1]), ("focus", thumbs[2]),
                                 width=thickness if vertical else minimum,
                                 height=minimum if vertical else thickness,
                                 border=(0, radius) if vertical else (radius, 0), sticky="nsew")
            style.layout(prefix + direction + ".TScrollbar", [(trough, {"sticky": "nsew", "children": [
                (thumb, {"sticky": "nsew", "expand": "1"})]})])
            name = prefix + direction + ".TScrollbar"
            style.configure(name, background=surface, troughcolor=surface, bordercolor=surface,
                            lightcolor=surface, darkcolor=surface, borderwidth=0, arrowsize=thickness,
                            width=thickness)
            style.map(name, background=[("disabled", surface), ("!disabled", surface)])

    # A scale remains a native ttk Scale: its own *slider/*trough targets keep
    # click increments, dragging, keyboard navigation and value callbacks.
    # Center a thin rail in the handle's hit area instead of painting a box.
    track_width, handle_width, handle_height = round(4 * scale), round(12 * scale), round(18 * scale)
    for direction in ("Horizontal", "Vertical"):
        horizontal = direction == "Horizontal"
        track_size = (64, track_width) if horizontal else (track_width, 64)
        handle_size = (handle_width, handle_height) if horizontal else (handle_height, handle_width)
        handles = [rounded_image(root, fill, outline, round(5 * scale), size=handle_size, line=scale)
                   for fill, outline in ((accent, accent), (t["accent_hover"], accent),
                                         (accent, t["selected_ink"]), (t["disabled_fg"], t["edge"]))]
        images.extend(handles)
        slider = "Dolly." + direction + ".Scale.slider"
        style.element_create(slider, "image", handles[0], ("disabled", handles[3]),
                             ("focus", handles[2]), ("pressed", handles[1]), ("active", handles[1]), sticky="")
        for prefix, surface in (("", bg), ("Card.", panel)):
            track = rounded_image(root, t["track"], t["track"], max(1, track_width // 2),
                                  size=track_size, line=0, surface=surface)
            images.append(track)
            trough = "Dolly." + prefix + direction + ".Scale.trough"
            style.element_create(trough, "image", track,
                                 border=(track_width // 2, 0) if horizontal else (0, track_width // 2),
                                 width=1 if horizontal else track_width,
                                 height=track_width if horizontal else 1,
                                 sticky="ew" if horizontal else "ns")
            style.layout(prefix + direction + ".TScale", [(trough, {"sticky": "nsew", "children": [
                (slider, {"side": "left" if horizontal else "top", "sticky": ""})]})])
            name = prefix + direction + ".TScale"
            style.configure(name, background=surface, borderwidth=0, relief="flat")
            style.map(name, background=[("disabled", surface), ("!disabled", surface)])
    style.configure("Treeview", borderwidth=0, relief="flat", bordercolor=panel, lightcolor=panel, darkcolor=panel)
    def surface_layout(layout):
        result = []
        for element, options in layout:
            options = dict(options)
            children = surface_layout(options.pop("children", []))
            if element in surfaces:
                # Sibling decoration does not borrow the field's 2px client
                # inset. All original content padding/hit areas stay intact.
                decorations = [(element + ".fill", {"sticky": "nsew"}),
                               *((element + "." + key, {"sticky": key}) for key in ("nw", "ne", "sw", "se")),
                               (element + ".minimum", {"sticky": ""})]
                children = decorations + children
            if children:
                options["children"] = children
            result.append((element, options))
        return result
    def inner_edge(fill, outline):
        amount = min(1., scale - 1.)
        return "#" + "".join(f"{round(a*(1-amount)+b*amount):02x}"
                            for a, b in zip(_rgb(fill), _rgb(outline)))
    surface_styles = ("Rounded.Card.TFrame", "UpdateNotice.Notes.TFrame", "TButton", "Primary.TButton",
                      "Card.TButton", "Card.Quiet.TButton", "Card.Primary.TButton", "UpdateNotice.TButton",
                      "UpdateNotice.Primary.TButton", "Curve.Axis.TButton", "Curve.Selected.Axis.TButton",
                      "Nav.TButton", "Selected.Nav.TButton", "Current.Nav.TButton", "TEntry", "Card.TEntry", "Numeric.TEntry",
                      "TCombobox", "Card.TCombobox", "TMenubutton", "Card.TMenubutton", "FullEditor.TCheckbutton")
    for name in surface_styles:
        layout = style.layout(name)
        paints = surfaces.get(layout[0][0])
        if paints is None:
            continue
        _, fill, outline = paints[0]
        style.configure(name, fieldbackground=fill, bordercolor=outline,
                        lightcolor=inner_edge(fill, outline), darkcolor=inner_edge(fill, outline))
        style.map(name, fieldbackground=[(state, color) for state, color, _ in paints[1:]],
                  bordercolor=[(state, edge) for state, _, edge in paints[1:]],
                  lightcolor=[(state, inner_edge(color, edge)) for state, color, edge in paints[1:]],
                  darkcolor=[(state, inner_edge(color, edge)) for state, color, edge in paints[1:]])
        style.layout(name, surface_layout(layout))
    root._dolly_theme_images = images


def install_wheel_guard(root):
    """Intercept before the ttk class binding can change a closed value."""
    def wheel(event):
        widget = event.widget
        # This handler is attached to value widgets only. Scroll their enclosing
        # page when possible; never synthesize a change to the selected value.
        parent = widget
        while parent is not None:
            if hasattr(parent, "scroll_page_wheel"):
                parent.scroll_page_wheel(event)
                break
            parent = getattr(parent, "master", None)
        return "break"
    # Replacing only the wheel class actions keeps dropdown opening, listbox
    # scrolling, keyboard arrows, and explicit selections unchanged.
    for cls in ("TCombobox", "TSpinbox", "Spinbox", "TScale", "Scale"):
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_class(cls, event, wheel)


def compact_slider(parent, label, variable, minimum, maximum, panel, muted, accent):
    """Compact rail with keyboard/drag adjustment and an exact editable value."""
    row = ttk.Frame(parent, style="Card.TFrame")
    row.pack(fill="x", pady=1)
    row.columnconfigure(1, weight=1)
    ttk.Label(row, text=label, style="CardMuted.TLabel", width=7).grid(row=0, column=0, sticky="w")
    rail = tk.Canvas(row, height=22, width=80, bg=panel, highlightthickness=0, takefocus=True)
    rail.grid(row=0, column=1, sticky="ew", padx=(4, 10))
    ttk.Entry(row, textvariable=variable, width=7, justify="right", style="Numeric.TEntry").grid(row=0, column=2)
    def redraw(*_):
        rail.delete("all")
        width = max(12, rail.winfo_width())
        try:
            value = float(variable.get())
        except (ValueError, tk.TclError):
            return
        if not math.isfinite(value):
            return
        x = 4 + (width - 8) * max(0, min(1, (value - minimum) / (maximum - minimum)))
        rail.create_line(4, 11, width - 4, 11, fill=ui_theme.TOKENS["field"], width=6, capstyle="round")
        rail.create_line(4, 11, x, 11, fill=ui_theme.TOKENS["accent_active"], width=6, capstyle="round")
        rail.create_line(x, 7, x, 15, fill=accent, width=5, capstyle="round")
        if rail.focus_get() == rail:
            rail.create_rectangle(1, 1, width - 1, 21, outline=muted)
    def set_value(value):
        variable.set(f"{max(minimum, min(maximum, value)):.2f}".rstrip("0").rstrip("."))
    def drag(event):
        rail.focus_set()
        set_value(minimum + (maximum - minimum) * (event.x - 4) / max(1, rail.winfo_width() - 8))
    def key(event):
        try:
            value = float(variable.get())
        except ValueError:
            value = minimum
        step = (maximum - minimum) / (1000 if event.state & 1 else 100)
        if event.keysym in ("Left", "Down"):
            set_value(value - step)
        elif event.keysym in ("Right", "Up"):
            set_value(value + step)
        elif event.keysym == "Home":
            set_value(minimum)
        elif event.keysym == "End":
            set_value(maximum)
        else:
            return
        return "break"
    token = variable.trace_add("write", redraw)
    rail.bind("<Configure>", redraw)
    rail.bind("<FocusIn>", redraw)
    rail.bind("<FocusOut>", redraw)
    rail.bind("<Button-1>", drag)
    rail.bind("<B1-Motion>", drag)
    rail.bind("<KeyPress>", key)
    rail.bind("<Destroy>", lambda event: variable.trace_remove("write", token))
    return row
