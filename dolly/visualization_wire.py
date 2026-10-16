"""Bounded, optional path guides for the native editor's existing DX11 overlay.

The separate ``<native mapping name>.viewer`` mapping is at most 2 MiB. A
64-byte little-endian header is followed by authored key times, bounded
per-key authoring metadata, and an unchanged native camera path. The publishing transport writes an odd sequence at offset
8 before replacing a packet, then commits its even sequence. This module only
builds immutable packets; it never accesses the game or evaluates per frame.
"""

from __future__ import annotations

import struct

from .native_path import MAX_CAMERA_KEYS, compile_project
from .path import Project, channel_value

MAGIC = b"DLYVIS01"
ABI = 3
MAPPING_BYTES = 2 * 1024 * 1024
HEADER = struct.Struct("<8s9IQ3I")
KEY_METADATA = struct.Struct("<7dII")
HEADER_BYTES = HEADER.size
SEQUENCE_OFFSET = 8
MAX_SAMPLES = 4096
MAX_MARKERS = 128
DEFAULT_SAMPLES = 2048
DEFAULT_MARKERS = 64


def _integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def build_visualization(project: Project | None, *, sequence=2, enabled=True,
                        selected_camera=0, sample_budget=DEFAULT_SAMPLES,
                        marker_budget=DEFAULT_MARKERS, revision=0, session_id=0) -> bytes:
    """Build a viewer packet without modifying a shot or its playback curves.

    Empty shots produce a clearing packet. Large shots keep every camera's
    position in the sampled line; glyphs are evenly spaced and always include
    the selected camera. This budget changes only drawing, never playback.
    """
    revision = _integer(revision, "Shot revision", 0, 0xFFFFFFFF)
    session_id = _integer(session_id, "Shot session", 0, 0xFFFFFFFFFFFFFFFF)
    sequence = _integer(sequence, "Viewer sequence", 2, 0xFFFFFFFE)
    if sequence & 1:
        raise ValueError("Viewer sequence must be even")
    if not isinstance(enabled, bool):
        raise ValueError("Viewer enabled must be a boolean")
    selected_camera = _integer(selected_camera, "Selected camera", 0, MAX_CAMERA_KEYS - 1)
    sample_budget = _integer(sample_budget, "Viewer sample budget", 2, MAX_SAMPLES)
    marker_budget = _integer(marker_budget, "Viewer marker budget", 1, MAX_MARKERS)
    if project is not None and not isinstance(project, Project):
        raise ValueError("Viewer compilation requires a Project")
    keys = project.keyframes if project is not None else []
    if not enabled or not keys:
        return HEADER.pack(MAGIC, sequence, ABI, 0, 0, 0, 0, sample_budget, marker_budget, revision, session_id, 0, 0, 0)
    payload = compile_project(project)
    if selected_camera >= len(keys):
        raise ValueError("Selected camera is outside this shot")
    budget = max(sample_budget, len(keys))
    result = bytearray(HEADER.pack(MAGIC, sequence, ABI, 1, selected_camera,
                         len(keys), len(payload), budget, marker_budget, revision, session_id,
                         len(keys) * KEY_METADATA.size, int(project.rotation_mode == "unwrapped"), 0))
    result += struct.pack(f"<{len(keys)}d", *(float(key.time) for key in keys))
    from .native_path import CHANNELS
    for key in keys:
        result += KEY_METADATA.pack(*(float(channel_value(key, name)) for name in CHANNELS),
                                    int(key.source == "attach"), 0)
    result += payload
    if len(result) > MAPPING_BYTES:
        raise ValueError("Viewer packet exceeds its fixed mapping size")
    return bytes(result)
