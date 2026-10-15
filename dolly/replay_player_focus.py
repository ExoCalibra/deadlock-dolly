"""Move native freecam near a verified replay player without changing replay time."""
import struct
import math

from ._runtime_generated import FollowTarget as profile
from .attach_camera import decode_view_offset
from .follow_target import FollowTargetMonitor


def resolve_player(monitor, identifier, players):
    # DemoFile PlayerIndex is the controller entity index, not the pawn's
    # roster position. Reuse the exact-build identity fields already reviewed
    # by FollowTargetMonitor; never guess a roster index from the kill list.
    if type(identifier) is not int or not 0 < identifier < 0x7fff:
        raise ValueError('Choose a valid replay player.')
    monitor._owned()
    reads = []

    def read(address, size):
        value = monitor.memory.read(address, size)
        reads.append((address, value))
        return value

    def pointer(address):
        return struct.unpack('<Q', read(address, 8))[0]

    system = pointer(monitor.base + profile.ENTITY_LIST)
    chunk = pointer(system + 8 * (identifier >> 9)) if system else 0
    if not chunk:
        raise RuntimeError('This player is not available at the current replay tick.')
    identity = chunk + profile.IDENTITY_STRIDE * (identifier & 0x1ff)
    controller = pointer(identity)
    handle = struct.unpack('<I', read(identity + profile.IDENTITY_HANDLE, 4))[0]
    if (not controller or handle & 0x7fff != identifier
            or pointer(controller + profile.ENTITY_IDENTITY) != identity
            or pointer(controller) != monitor.base + profile.CONTROLLER_VTABLE):
        raise RuntimeError('The selected player controller changed. Select the player again.')
    pawn = struct.unpack('<I', read(controller + profile.CONTROLLER_PAWN, 4))[0]
    matches = [dict(player) for player in players
               if player.get('handle') == pawn and player.get('entity_index') == pawn & 0x7fff]
    if len(matches) != 1 or any(monitor.memory.read(address, len(value)) != value
                               for address, value in reads):
        raise RuntimeError('This hero is not available at the current tick. Seek to a live moment.')
    monitor._owned()
    return matches[0]


def player_freecam_pose(monitor, player, fields, current_pose):
    """Read a fresh pawn's eye position; compose a nearby independent view."""
    required = ('scene_node', 'owner', 'player_origin', 'player_angles', 'eye_offset', 'eye_angles')
    if not isinstance(fields, dict) or any(type(fields.get(key)) is not int or
            not 8 <= fields[key] <= 0x8000 for key in required):
        raise RuntimeError('Player camera fields are not ready. Wait for camera setup to complete.')
    if (not isinstance(current_pose,(tuple,list)) or len(current_pose) != 7
            or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e8 for v in current_pose)
            or not .25 <= current_pose[6] <= 8):
        raise RuntimeError('The current free-camera view is unavailable.')
    monitor._owned()
    reads = []
    def read(address, size):
        data = monitor.memory.read(address, size)
        reads.append((address,data))
        return data
    def pointer(address):
        return struct.unpack('<Q',read(address,8))[0]
    handle = player['handle']
    system = pointer(monitor.base + profile.ENTITY_LIST)
    chunk = pointer(system + 8*((handle & 0x7fff) >> 9)) if system else 0
    if not chunk:
        raise RuntimeError('The selected player is unavailable at this tick.')
    identity = chunk + profile.IDENTITY_STRIDE*(handle & 0x1ff)
    pawn = pointer(identity)
    if (not pawn or struct.unpack('<I',read(identity+profile.IDENTITY_HANDLE,4))[0] != handle
            or pointer(pawn+profile.ENTITY_IDENTITY) != identity
            or pointer(pawn) not in (monitor.base+profile.PLAYER_PAWN_VTABLE,
                                    monitor.base+profile.FAMILIAR_CLONE_PAWN_VTABLE)):
        raise RuntimeError('The selected player changed. Select the player again.')
    node = pointer(pawn+fields['scene_node'])
    if not node or pointer(node+fields['owner']) != pawn:
        raise RuntimeError('The selected player scene changed. Select the player again.')
    origin = struct.unpack('<3f',read(node+fields['player_origin'],12))
    angles = struct.unpack('<3f',read(node+fields['player_angles'],12))
    aim = struct.unpack('<3f',read(pawn+fields['eye_angles'],12))
    local = decode_view_offset(read(pawn+fields['eye_offset'],36))
    if (local is None or any(not math.isfinite(v) or abs(v)>1e8 for v in origin)
            or any(not math.isfinite(v) or abs(v)>36000 for v in angles+aim)):
        raise RuntimeError('The selected player position is unavailable.')
    if any(monitor.memory.read(address,len(data)) != data for address,data in reads):
        raise RuntimeError('The selected player moved during camera sampling. Select them again.')
    monitor._owned()
    # Source's same forward/right/up basis used by the native attach sampler.
    pitch,yaw,roll = map(math.radians,angles)
    sp,cp,sy,cy,sr,cr = math.sin(pitch),math.cos(pitch),math.sin(yaw),math.cos(yaw),math.sin(roll),math.cos(roll)
    forward=(cp*cy,cp*sy,-sp)
    right=(-sr*sp*cy+cr*sy,-sr*sp*sy-cr*cy,-sr*cp)
    up=(cr*sp*cy+sr*sy,cr*sp*sy-sr*cy,cr*cp)
    eye=tuple(origin[i]+forward[i]*local[0]+right[i]*local[1]+up[i]*local[2] for i in range(3))
    heading=math.radians(aim[1])
    x,y,z=eye[0]-160*math.cos(heading),eye[1]-160*math.sin(heading),eye[2]+24
    return dict(x=x,y=y,z=z,pitch=math.degrees(math.atan2(24,160)),yaw=aim[1],
                roll=current_pose[5],aspect_ratio=current_pose[6])


def focus_replay_player(controller, identifier, fields=None):
    with controller._op_lock:
        controller._require_quiet_session('moving free camera to a player')
        controller._require_demo(require_tick=False)
        bridge = controller._native_bridge()
        bridge.require_capability('camera')
        before = bridge.status()
        if not before.get('paused') or controller._recorder_active():
            raise RuntimeError('Pause the replay and finish recording before selecting a player.')
        monitor = FollowTargetMonitor(controller._session)
        try:
            roster = bridge.editor_roster() or {}
            player = resolve_player(monitor, identifier, roster.get('players', []))
            pose = player_freecam_pose(monitor, player, fields, before.get('applied_pose', ()))
            fresh = resolve_player(monitor, identifier, (bridge.editor_roster() or {}).get('players', []))
            current = bridge.status()
            if fresh != player or not current.get('paused') or current.get('tick') != before.get('tick'):
                raise RuntimeError('The player or replay changed during camera sampling. Select them again.')
        finally:
            monitor.close()
        controller.enter_native_flight(pose=pose, owner='panel')
        controller._freecam_player_evidence = dict(player_id=identifier, handle=player['handle'],
                                                 tick=before.get('tick'), pose=pose)
