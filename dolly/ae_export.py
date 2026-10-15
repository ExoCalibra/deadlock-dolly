"""On export, create an After Effects ExtendScript (.jsx) with camera data

Camera data saved per frame. Falls back to using keyframes when no camera data is available.

AE uses left handed cartesian coordinates
pos:      (x, y, z) -> (x, -z, y)
rotation: (x, y, z) -> (Rx, Ry, Rz)
fov:      2 * atan(lens_scale * aspect_ratio)
"""
# TODO: Fix comp size - only works for 16:9

from __future__ import annotations

import json
import math
from pathlib import Path

from .path import Project

DEFAULT_LENS = .75
DEFAULT_COMP = 1920
GIMBAL = 1 - 1e-9 # gimbal lock floating point rounding errors
CAMERA_FIELDS = ["frame", "video_time", "phase", "x", "y", "z", "pitch", "yaw", "roll", "horizontal_fov"]


def ae_vector(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Source vector to After Effects vector."""
    return (x, -z, y)


def ae_rotation(pitch: float, yaw: float, roll: float) -> list[tuple[float, float, float]]:
    """Source to AE camera rotation"""
    forward, right, up = angle_vectors(pitch, yaw, roll)
    columns = (ae_vector(*right), tuple(-v for v in ae_vector(*up)), ae_vector(*forward))
    matrix = [[columns[col][row] for col in range(3)] for row in range(3)]
    return euler_candidates(matrix)


def angle_vectors(pitch: float, yaw: float, roll: float):
    """Source angle vectors: forward, right and up."""
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    forward = (cp * cy, cp * sy, -sp)
    right = (-sr * sp * cy + cr * sy, -sr * sp * sy - cr * cy, -sr * cp)
    up = (cr * sp * cy + sr * sy, cr * sp * sy - sr * cy, cr * cp)
    return forward, right, up


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


def horizontal_fov(lens_scale: float, aspect_ratio: float) -> float:
    """Horizontal FOV in degrees"""
    fov = math.degrees(2 * math.atan(lens_scale * aspect_ratio))
    if not math.isfinite(fov) or not 1 < fov < 179:
        raise ValueError(f"Invalid FOV ({fov})")
    return fov


def comp_size(standard_aspect: float, width: int = DEFAULT_COMP) -> tuple[int, int]:
    """Default comp size for the shot's standard aspect, with an even height."""
    height = max(2, int(round(width / standard_aspect / 2)) * 2)
    return width, height


def sample_camera(project: Project, fps: float):
    """Return per-frame AE camera data"""
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"Invalid fps ({fps})")
    
    project.validate()
    if not project.keyframes:
        raise ValueError("Add a camera keyframe before exporting the camera.")
        
    duration = project.duration
    count = int(math.floor(duration * fps + 1e-9)) + 1
    has_lens = any(key.lens_scale is not None for key in project.keyframes)
    samples = []
    previous = None

    for index in range(count):
        time = index / fps
        pose = project.evaluate(time)
        lens = pose["lens_scale"] if has_lens else DEFAULT_LENS
        rotation = continuous(ae_rotation(pose["pitch"], pose["yaw"], pose["roll"]), previous)
        previous = rotation
        samples.append({"frame": index, "time": time,
                        "position": ae_vector(pose["x"], pose["y"], pose["z"]),
                        "rotation": rotation, "fov": horizontal_fov(lens, pose["aspect_ratio"])})
   
    warnings = []
    if any(key.source == "attach" for key in project.keyframes):
        warnings.append("Attach keys are currently unsupported.")
    if not has_lens:
        warnings.append("No captured lens, assuming a standard 90-degree spectator lens.")

    return samples, warnings


def sample_camera_data(path: str | Path, fps: float):
    """Samples saved camera data"""
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"Invalid fps ({fps})")
    data = json.loads(Path(path).read_text("utf-8"))
    if (not isinstance(data, dict) or data.get("format") != "deadlock-dolly-camera"
            or data.get("version") != 1 or data.get("fields") != CAMERA_FIELDS):
        raise ValueError("Not a supported camera path")
    rows = data.get("frames")
    if not isinstance(rows, list) or not rows:
        raise ValueError("The camera data has no frames")

    samples = []
    previous = None
    last_frame = -1
    for row in rows:
        if (not isinstance(row, list) or len(row) != len(CAMERA_FIELDS) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in row)):
            raise ValueError("The camera data has an invalid frame")
        _, video_time, _, x, y, z, pitch, yaw, roll, fov = row
        frame = round(video_time * fps)
        if frame <= last_frame or not 1 < fov < 179:
            raise ValueError("The camera data has an invalid frame")
        last_frame = frame
        rotation = continuous(ae_rotation(pitch, yaw, roll), previous)
        previous = rotation
        samples.append({"frame": frame, "time": frame / fps, "position": ae_vector(x, y, z), "rotation": rotation, "fov": fov})

    written = data.get("frames_written")
    video_frames = written if isinstance(written, int) and written > last_frame else last_frame + 1
    return samples, video_frames


def build_jsx(project: Project, fps: float, *, camera_data: str | Path | None = None,
              width: int | None = None, height: int | None = None) -> tuple[str, list[str]]:
    """Return the JSX source and accuracy warnings for a shot.

    With the native camera available, every frame is sampled; otherwise the
    path is sampled from its keyframes.
    """
    if camera_data is not None:
        samples, video_frames = sample_camera_data(camera_data, fps)
        warnings = []
    else:
        samples, warnings = sample_camera(project, fps)
        video_frames = len(samples)
    default_width, default_height = comp_size(project.standard_aspect)
    width, height = width or default_width, height or default_height
    
    # Positions are offsets from the first frame's camera,
    origin = samples[0]["position"]
    def offset(position):
        return tuple(value - base for value, base in zip(position, origin))

    keys = [(float(key.time), offset(ae_vector(key.x, key.y, key.z))) for key in project.keyframes]
    data = {
        "frame_numbers": array(str(s["frame"]) for s in samples),
        "positions": array(array(map(number, offset(s["position"]))) for s in samples),
        "rotations": array(array(map(number, s["rotation"])) for s in samples),
        "fovs": array(number(s["fov"]) for s in samples),
        "keys": array(array([number(t), *map(number, p)]) for t, p in keys),
        "origin": array(map(number, origin)),
    }
    name = json.dumps(project.name, ensure_ascii=True)
    script = f"""// Dolly camera for After Effects.
// Run with File > Scripts > Run Script File...
(function () {{
    var COMP_WIDTH = {int(width)};
    var COMP_HEIGHT = {int(height)};
    var SCALE = 1.0;
    var ADD_KEY_MARKERS = true;

    var SHOT_NAME = {name};
    var FPS = {number(float(fps))};
    var FRAMES = {video_frames};
    var ORIGIN = {data["origin"]};
    var frameNumbers = {data["frame_numbers"]};
    var positions = {data["positions"]};
    var rotations = {data["rotations"]};
    var fovs = {data["fovs"]};
    var dollyKeys = {data["keys"]};

    app.beginUndoGroup("Import Dolly camera");
    try {{
        var comp = app.project.items.addComp(SHOT_NAME + " (Dolly Camera)", COMP_WIDTH, COMP_HEIGHT,
                                             1, FRAMES / FPS, FPS);
        // Markers first so the camera sits above them in the layer stack.
        if (ADD_KEY_MARKERS) {{
            for (var k = 0; k < dollyKeys.length; k++) {{
                var key = dollyKeys[k];
                var marker = comp.layers.addNull();
                marker.name = "Dolly key " + (k + 1) + " @ " + key[0].toFixed(3) + "s";
                marker.threeDLayer = true;
                marker.guideLayer = true;
                marker.property("ADBE Transform Group").property("ADBE Position")
                    .setValue([key[1] * SCALE, key[2] * SCALE, key[3] * SCALE]);
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
    return script, warnings


def export_jsx(project: Project, path: str | Path, fps: float, **options) -> list[str]:
    """Write the script"""
    import os
    import tempfile

    script, warnings = build_jsx(project, fps, **options)
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
    return warnings


# Helpers
def number(value: float) -> str:
    """Rounding numbers to 6 decimals"""
    return format(round(value, 6), ".10g")


def array(values) -> str:
    return "[" + ",".join(values) + "]"
