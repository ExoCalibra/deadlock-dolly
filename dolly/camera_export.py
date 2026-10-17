"""
Camera data saved per frame. Falls back to using keyframes when no camera data is available.

AE uses left handed cartesian coordinates
pos:      (x, y, z) -> (x, -z, y)
rotation: (x, y, z) -> (Rx, Ry, Rz)
fov:      2 * atan(lens_scale * aspect_ratio)

USD (.usda)
pos:      (x, y, z) -> (x, y, z)
rotation: (x, y, z), R = Rz * Ry * Rx
fov:      (horizontalAperture / 2) / tan(fov / 2)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import NamedTuple

from .path import Project

DEFAULT_LENS = .75
DEFAULT_COMP = 1920
GIMBAL = 1 - 1e-9 # gimbal lock floating point rounding errors
CAMERA_FIELDS = ["frame", "video_time", "phase", "x", "y", "z", "pitch", "yaw", "roll", "horizontal_fov"]


class Frame(NamedTuple):
    """One video frame's camera."""
    frame: int
    time: float  # seconds
    position: tuple[float, float, float]
    angles: tuple[float, float, float]  # pitch, yaw, roll
    fov: float  # horizontal, degrees
    phase: float


class Marker(NamedTuple):
    """Where the camera was when the shot reached one keyframe."""
    key: int  # keyframe
    time: float  # video seconds
    position: tuple[float, float, float]


class Take(NamedTuple):
    """Every sampled frame, the video length in frames, accuracy warnings and keyframe markers."""
    frames: list[Frame]
    video_frames: int
    warnings: list[str]
    markers: tuple[Marker, ...] = ()


def angle_vectors(pitch: float, yaw: float, roll: float):
    """Vectors: forward, right and up."""
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    forward = (cp * cy, cp * sy, -sp)
    right = (-sr * sp * cy + cr * sy, -sr * sp * sy - cr * cy, -sr * cp)
    up = (cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp)
    return forward, right, up


def horizontal_fov(lens_scale: float, aspect_ratio: float) -> float:
    """Horizontal FOV in degrees"""
    fov = math.degrees(2 * math.atan(lens_scale * aspect_ratio))
    if not math.isfinite(fov) or not 1 < fov < 179:
        raise ValueError(f"Invalid FOV ({fov})")
    return fov


def comp_size(standard_aspect: float, width: int = DEFAULT_COMP) -> tuple[int, int]:
    """The shot's standard aspect, with an even height."""
    height = max(2, int(round(width / standard_aspect / 2)) * 2)
    return width, height


def sample_camera(project: Project, fps: float, speed: float = 1.0,
                  video_frames: int | None = None) -> Take:
    """Sample the camera data once per video frame."""
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"Invalid fps ({fps})")
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError(f"Invalid export speed ({speed})")
    if video_frames is not None and video_frames < 1:
        raise ValueError(f"Invalid frame count ({video_frames})")

    project.validate()
    if not project.keyframes:
        raise ValueError("Add a camera keyframe before exporting the camera.")

    duration = project.duration / speed
    count = int(math.floor(duration * fps + 1e-9)) + 1
    if video_frames is not None:
        count = min(count, video_frames)
    has_lens = any(key.lens_scale is not None for key in project.keyframes)
    frames = []

    for index in range(count):
        time = index / fps
        pose = project.evaluate(time * speed)
        lens = pose["lens_scale"] if has_lens else DEFAULT_LENS
        frames.append(Frame(index, time, (pose["x"], pose["y"], pose["z"]),
                            (pose["pitch"], pose["yaw"], pose["roll"]),
                            horizontal_fov(lens, pose["aspect_ratio"]), time * speed))

    warnings = []
    if any(key.source == "attach" for key in project.keyframes):
        warnings.append("Attach keys are currently unsupported; their markers are left out.")
    if not has_lens:
        warnings.append("No captured lens, assuming a standard 90-degree lens.")

    return Take(frames, video_frames or len(frames), warnings)


def sample_camera_data(path: str | Path, fps: float) -> Take:
    """Samples saved camera data"""
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"Invalid fps ({fps})")
    data = json.loads(Path(path).read_text("utf-8"))
    if (not isinstance(data, dict) or data.get("format") != "deadlock-dolly-camera-track"
            or data.get("version") != 1 or data.get("fields") != CAMERA_FIELDS):
        raise ValueError("Not a supported camera path")
    rows = data.get("frames")
    if not isinstance(rows, list) or not rows:
        raise ValueError("The camera data has no frames")

    frames = []
    last_frame = -1
    for row in rows:
        if (not isinstance(row, list) or len(row) != len(CAMERA_FIELDS) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in row)):
            raise ValueError("The camera data has an invalid frame")
        _, video_time, phase, x, y, z, pitch, yaw, roll, fov = row
        frame = round(video_time * fps)
        if frame <= last_frame or not 1 < fov < 179:
            raise ValueError("The camera data has an invalid frame")
        last_frame = frame
        frames.append(Frame(frame, frame / fps, (x, y, z), (pitch, yaw, roll), fov, phase))

    written = data.get("frames_written")
    video_frames = written if isinstance(written, int) and written > last_frame else last_frame + 1
    return Take(frames, video_frames, [])


def load_take(project: Project, fps: float, camera_data: str | Path | None = None,
              speed: float = 1.0, video_frames: int | None = None, pov: bool = False) -> Take:
    """Saved camera data when available; otherwise the shot's keyframes."""
    if pov:
        if camera_data is None:
            raise ValueError("Player POV recording saved no camera data")
        return sample_camera_data(camera_data, fps)
    if camera_data is not None:
        take = sample_camera_data(camera_data, fps)
    else:
        take = sample_camera(project, fps, speed, video_frames)
    return take._replace(markers=key_markers(project, take.frames, camera_data is not None))


def key_markers(project: Project, frames: list[Frame], recorded: bool) -> tuple[Marker, ...]:
    """A marker for every keyframe in the take."""
    markers = []
    for number, key in enumerate(project.keyframes, start=1):
        if recorded:
            arrival = arrival_at(frames, float(key.time))
            if arrival is not None:
                markers.append(Marker(number, *arrival))
        elif key.source != "attach":
            arrival = arrival_at(frames, float(key.time))
            if arrival is not None:  # An early finish never reaches the later keys.
                markers.append(Marker(number, arrival[0], (key.x, key.y, key.z)))
    return tuple(markers)


def arrival_at(frames: list[Frame], phase: float):
    """Time and camera position when the shot reached a certain phase, or None if it never did."""
    step = abs(frames[-1].phase - frames[-2].phase) if len(frames) > 1 else 0.0
    if frames[0].phase - step <= phase < frames[0].phase:
        return frames[0].time, frames[0].position
    for before, after in zip(frames, frames[1:]):
        if before.phase <= phase <= after.phase:
            span = after.phase - before.phase
            weight = (phase - before.phase) / span if span > 0 else 0.0
            return (before.time + (after.time - before.time) * weight,
                    tuple(a + (b - a) * weight for a, b in zip(before.position, after.position)))
    if frames[-1].phase <= phase <= frames[-1].phase + step:
        return frames[-1].time, frames[-1].position
    return None


# After Effects (.jsx)
def ae_vector(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Source vector to After Effects vector."""
    return (x, -z, y)


def ae_rotation(pitch: float, yaw: float, roll: float) -> list[tuple[float, float, float]]:
    """Source to AE camera rotation"""
    forward, right, up = angle_vectors(pitch, yaw, roll)
    columns = (ae_vector(*right), tuple(-v for v in ae_vector(*up)), ae_vector(*forward))
    matrix = [[columns[col][row] for col in range(3)] for row in range(3)]
    return euler_candidates(matrix)


def euler_candidates(matrix) -> list[tuple[float, float, float]]:
    """Returns both solutions of R = Rx(a) * Ry(b) * Rz(c), in degrees."""
    r02 = max(-1.0, min(1.0, matrix[0][2]))
    if abs(r02) >= GIMBAL: # Gimbal lock
        b = math.copysign(90.0, r02)
        a = math.degrees(math.atan2(matrix[2][1], matrix[1][1]))
        return [(a, b, 0.0)]
    b = math.asin(r02)
    a = math.atan2(-matrix[1][2], matrix[2][2])
    c = math.atan2(-matrix[0][1], matrix[0][0])
    first = (math.degrees(a), math.degrees(b), math.degrees(c))
    second = (first[0] + 180.0, 180.0 - first[1], first[2] + 180.0)
    return [first, second]


def nearest(value: float, previous: float) -> float:
    return value - 360.0 * round((value - previous) / 360.0)


def continuous(candidates, previous):
    """Pick the euler candidate closest to the previous frame."""
    if previous is None:
        return candidates[0]
    best = None
    for candidate in candidates:
        unwrapped = tuple(nearest(v, p) for v, p in zip(candidate, previous))
        distance = sum((v - p) ** 2 for v, p in zip(unwrapped, previous))
        if best is None or distance < best[0]:
            best = (distance, unwrapped)
    return best[1]


def ae_rotations(frames: list[Frame]) -> list[tuple[float, float, float]]:
    """AE x,y,z Rotation for every frame, continuous from frame to frame."""
    rotations = []
    previous = None
    for frame in frames:
        previous = continuous(ae_rotation(*frame.angles), previous)
        rotations.append(previous)
    return rotations


def build_jsx(project: Project, fps: float, *, camera_data: str | Path | None = None,
              width: int | None = None, height: int | None = None,
              speed: float = 1.0, video_frames: int | None = None,
              video: str | None = None, pov: bool = False) -> tuple[str, list[str]]:
    """Return the JSX source and accuracy warnings for a shot.

    With the native camera available, every frame is sampled; otherwise the
    path is sampled from its keyframes. Video is the recorded file's name,
    which the script imports from its own folder.
    """
    take = load_take(project, fps, camera_data, speed, video_frames, pov)
    frames = take.frames
    default_width, default_height = comp_size(project.standard_aspect)
    width, height = width or default_width, height or default_height

    # Positions are offsets from the first frame's camera,
    origin = ae_vector(*frames[0].position)
    def offset(position):
        return tuple(value - base for value, base in zip(ae_vector(*position), origin))

    keys = [(marker.key, marker.time, offset(marker.position)) for marker in take.markers]
    data = {
        "frame_numbers": array(str(f.frame) for f in frames),
        "positions": array(array(map(number, offset(f.position))) for f in frames),
        "rotations": array(array(map(number, r)) for r in ae_rotations(frames)),
        "fovs": array(number(f.fov) for f in frames),
        "keys": array(array([str(n), number(t), *map(number, p)]) for n, t, p in keys),
        "origin": array(map(number, origin)),
    }
    name = json.dumps(project.name, ensure_ascii=True)
    video_name = json.dumps(video, ensure_ascii=True) if video else "null"
    script = f"""// Dolly camera for After Effects.
// Run with File > Scripts > Run Script File...
(function () {{
    var COMP_WIDTH = {int(width)};
    var COMP_HEIGHT = {int(height)};
    var SCALE = 1.0;
    var ADD_KEY_MARKERS = true;
    var IMPORT_VIDEO = true;

    var SHOT_NAME = {name};
    var VIDEO_FILE = {video_name};
    var FPS = {number(float(fps))};
    var FRAMES = {take.video_frames};
    var ORIGIN = {data["origin"]};
    var frameNumbers = {data["frame_numbers"]};
    var positions = {data["positions"]};
    var rotations = {data["rotations"]};
    var fovs = {data["fovs"]};
    var dollyKeys = {data["keys"]};

    function importVideo() {{
        var file = $.fileName ? new File(new File($.fileName).parent.fsName + "/" + VIDEO_FILE) : null;
        if (!file || !file.exists) {{
            file = File.openDialog("Locate " + VIDEO_FILE + " for " + SHOT_NAME);
            if (!file) return null;
        }}
        var item = null;
        for (var n = 1; n <= app.project.numItems && !item; n++) {{
            var candidate = app.project.item(n);
            if (candidate instanceof FootageItem && candidate.file && candidate.file.fsName === file.fsName)
                item = candidate;
        }}
        item = item || app.project.importFile(new ImportOptions(file));
        // One video frame per comp frame, so each frame meets its camera key.
        item.mainSource.conformFrameRate = FPS;
        return item;
    }}

    app.beginUndoGroup("Import Dolly camera");
    try {{
        var footage = IMPORT_VIDEO && VIDEO_FILE ? importVideo() : null;
        if (footage) {{
            COMP_WIDTH = footage.width;
            COMP_HEIGHT = footage.height;
        }}
        var comp = app.project.items.addComp(SHOT_NAME + " (Dolly Camera)", COMP_WIDTH, COMP_HEIGHT,
                                             1, FRAMES / FPS, FPS);
        // Camera, markers, and video layers
        if (footage) comp.layers.add(footage);
        if (ADD_KEY_MARKERS) {{
            for (var k = 0; k < dollyKeys.length; k++) {{
                var key = dollyKeys[k]; // [key number, video seconds, x, y, z]
                var marker = comp.layers.addNull();
                marker.name = "Dolly key " + key[0] + " @ " + key[1].toFixed(3) + "s";
                marker.threeDLayer = true;
                marker.guideLayer = true;
                marker.property("ADBE Transform Group").property("ADBE Position")
                    .setValue([key[2] * SCALE, key[3] * SCALE, key[4] * SCALE]);
            }}
        }}
        var camera = comp.layers.addCamera("Dolly camera", [COMP_WIDTH / 2, COMP_HEIGHT / 2]);
        camera.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
        var times = [], scaled = [], xs = [], ys = [], zs = [], zooms = [];
        for (var i = 0; i < positions.length; i++) {{
            var p = positions[i], r = rotations[i];
            times.push(frameNumbers[i] / FPS);
            scaled.push([p[0] * SCALE, p[1] * SCALE, p[2] * SCALE]);
            xs.push(r[0]); ys.push(r[1]); zs.push(r[2]);
            zooms.push((COMP_WIDTH / 2) / Math.tan(fovs[i] * Math.PI / 360));
        }}
        var transform = camera.property("ADBE Transform Group");
        transform.property("ADBE Position").setValuesAtTimes(times, scaled);
        transform.property("ADBE Orientation").setValue([0, 0, 0]);
        transform.property("ADBE Rotate X").setValuesAtTimes(times, xs);
        transform.property("ADBE Rotate Y").setValuesAtTimes(times, ys);
        transform.property("ADBE Rotate Z").setValuesAtTimes(times, zs);
        camera.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValuesAtTimes(times, zooms);
        comp.openInViewer();
    }} catch (error) {{
        alert("Dolly camera import failed: " + error.toString());
    }} finally {{
        app.endUndoGroup();
    }}
}})();
"""
    return script, take.warnings


def export_jsx(project: Project, path: str | Path, fps: float, **options) -> list[str]:
    """Write the script"""
    script, warnings = build_jsx(project, fps, **options)
    write_script(path, script)
    return warnings


# USD (.usda)
USD_APERTURE = 36.0 # horizontal aperture
USD_METERS_PER_UNIT = 0.0254 # one unit is about an inch


def usd_rotation(pitch: float, yaw: float, roll: float) -> list[tuple[float, float, float]]:
    """Both rotatation solutions (R = Rz * Ry * Rx, degrees)"""
    forward, right, up = angle_vectors(pitch, yaw, roll)
    columns = (right, up, tuple(-v for v in forward)) # USD cameras look down -Z
    m = [[columns[col][row] for col in range(3)] for row in range(3)]
    r20 = max(-1.0, min(1.0, m[2][0]))
    if abs(r20) >= GIMBAL: # Gimbal lock
        b = -math.copysign(90.0, r20)
        a = math.degrees(math.atan2(-m[1][2], m[1][1]))
        return [(a, b, 0.0)]
    b = -math.asin(r20)
    a = math.atan2(m[2][1], m[2][2])
    c = math.atan2(m[1][0], m[0][0])
    first = (math.degrees(a), math.degrees(b), math.degrees(c))
    second = (first[0] + 180.0, 180.0 - first[1], first[2] + 180.0)
    return [first, second]


def usd_rotations(frames: list[Frame]) -> list[tuple[float, float, float]]:
    """Applies USD rotation conversion for eahc frame"""
    rotations = []
    previous = None
    for frame in frames:
        previous = continuous(usd_rotation(*frame.angles), previous)
        rotations.append(previous)
    return rotations


def usd_string(text: str) -> str:
    safe = "".join(c if " " <= c <= "~" else "?" for c in text)
    return '"' + safe.replace("\\", "\\\\").replace('"', '\\"') + '"'


def usd_tuple(values) -> str:
    return "(" + ", ".join(map(number, values)) + ")"


def usd_samples(frames: list[Frame], values) -> str:
    """Samples keyed by video frame."""
    rows = "".join(f"            {f.frame}: {v},\n" for f, v in zip(frames, values))
    return "{\n" + rows + "        }"


def build_usda(project: Project, fps: float, *, camera_data: str | Path | None = None,
               width: int | None = None, height: int | None = None,
               speed: float = 1.0, video_frames: int | None = None,
               pov: bool = False) -> tuple[str, list[str]]:
    """Return the USD stage and accuracy warnings for a shot."""
    take = load_take(project, fps, camera_data, speed, video_frames, pov)
    frames = take.frames
    default_width, default_height = comp_size(project.standard_aspect)
    width, height = width or default_width, height or default_height
    vertical_aperture = USD_APERTURE * height / width

    # Positions are offsets from the first frame's camera.
    origin = frames[0].position
    def offset(position):
        return tuple(value - base for value, base in zip(position, origin))

    translations = (usd_tuple(offset(f.position)) for f in frames)
    rotations = (usd_tuple(r) for r in usd_rotations(frames))
    focals = (number(USD_APERTURE / 2 / math.tan(math.radians(f.fov) / 2)) for f in frames)
    keys = "".join(f'''
        def Xform "Key_{marker.key:02d}" (
            doc = "Dolly key {marker.key} @ {marker.time:.3f}s"
        )
        {{
            double3 xformOp:translate = {usd_tuple(offset(marker.position))}
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }}
''' for marker in take.markers)
    layer = f"""#usda 1.0
(
    defaultPrim = "Dolly"
    doc = "Deadlock Dolly Camera"
    customLayerData = {{
        string shot = {usd_string(project.name)}
        double3 origin = {usd_tuple(origin)}
    }}
    metersPerUnit = {number(USD_METERS_PER_UNIT)}
    upAxis = "Z"
    framesPerSecond = {number(float(fps))}
    timeCodesPerSecond = {number(float(fps))}
    startTimeCode = 0
    endTimeCode = {max(0, take.video_frames - 1)}
)

def Xform "Dolly"
{{
    def Camera "Camera"
    {{
        token projection = "perspective"
        float2 clippingRange = (1, 1000000)
        float horizontalAperture = {number(USD_APERTURE)}
        float verticalAperture = {number(vertical_aperture)}
        float focalLength.timeSamples = {usd_samples(frames, focals)}
        double3 xformOp:translate.timeSamples = {usd_samples(frames, translations)}
        float3 xformOp:rotateXYZ.timeSamples = {usd_samples(frames, rotations)}
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
    }}

    def Xform "Keys"
    {{{keys}    }}
}}
"""
    return layer, take.warnings


def export_usda(project: Project, path: str | Path, fps: float, **options) -> list[str]:
    """Write the USD stage"""
    stage, warnings = build_usda(project, fps, **options)
    write_script(path, stage)
    return warnings


# Helpers
def write_script(path: str | Path, script: str) -> None:
    import os
    import tempfile

    destination = Path(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(script.encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def number(value: float) -> str:
    """Rounding numbers to 6 decimals"""
    return format(round(value, 6), ".10g")


def array(values) -> str:
    return "[" + ",".join(values) + "]"
