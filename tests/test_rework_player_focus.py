import unittest
import struct
import threading
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch

from dolly.editor_dispatch import _dispatch
from dolly.replay_events import KillIndex
from dolly.replay_player_focus import (resolve_player, focus_replay_player, player_freecam_pose,
    ReplayPlayerUnavailable, ReplayPlayerDeferred, ReplayPlayerPoseChanged, POSE_SAMPLE_ATTEMPTS)
from dolly.follow_camera import FollowSettings
from dolly._runtime_generated import FollowTarget as profile


class ReworkPlayerFocusTests(unittest.TestCase):
    def app(self):
        return SimpleNamespace(
            busy=False, preview_attach=False,
            controller=Mock(),
            _replay_events_cache=KillIndex(2, 10000, (), ((1, 'Ivy player'), (2, 'Haze player'))),
        )

    def test_selected_player_dispatches_one_verified_camera_operation(self):
        app = self.app()
        with patch('dolly.editor_dispatch._native_operation') as operation, \
                patch('dolly.replay_player_focus.focus_replay_player') as focus:
            try:
                _dispatch(app, {'action': 'focus_replay_player', 'value': 2}, object(), publish=lambda: None)
            except ValueError:
                pass
            self.assertEqual(operation.call_count, 1, 'Player selection must reach the verified camera handoff')
            operation.call_args.args[2]()
            app.controller.follow_replay_player.assert_called_once_with(2)
            focus.assert_not_called()  # The one-shot freecam API remains separate.

    def test_missing_world_or_fractional_player_cannot_move_camera(self):
        app = self.app()
        for player in (0, 3, 1.5, float('nan'), -1):
            with self.subTest(player=player), patch('dolly.editor_dispatch._native_operation') as operation:
                with self.assertRaises(ValueError):
                    _dispatch(app, {'action': 'focus_replay_player', 'value': player}, object(), publish=lambda: None)
                operation.assert_not_called()

    def test_loading_or_attach_preview_cannot_move_camera(self):
        app = self.app()
        for loading, attached in ((True, False), (False, True)):
            app.preview_attach = attached
            app._replay_events_cache = KillIndex(1 if loading else 2, 10000, (), ((1, 'Ivy player'),))
            with self.subTest(loading=loading, attached=attached), self.assertRaises(ValueError):
                _dispatch(app, {'action': 'focus_replay_player', 'value': 1}, object(), publish=lambda: None)

    def memory_fixture(self):
        base, system, chunk, controller = 0x1000, 0x60000, 0x80000, 0xa0000
        identity = chunk + profile.IDENTITY_STRIDE
        pawn = 0x1004c
        fields = {
            (base + profile.ENTITY_LIST, 8): struct.pack('<Q', system),
            (system, 8): struct.pack('<Q', chunk),
            (identity, 8): struct.pack('<Q', controller),
            (identity + profile.IDENTITY_HANDLE, 4): struct.pack('<I', 0x10001),
            (controller + profile.ENTITY_IDENTITY, 8): struct.pack('<Q', identity),
            (controller, 8): struct.pack('<Q', base + profile.CONTROLLER_VTABLE),
            (controller + profile.CONTROLLER_PAWN, 4): struct.pack('<I', pawn),
        }
        pawn_identity = chunk + profile.IDENTITY_STRIDE * (pawn & 0x1ff)
        pawn_instance = 0xc0000
        fields.update({
            (pawn_identity, 8): struct.pack('<Q', pawn_instance),
            (pawn_identity + profile.IDENTITY_HANDLE, 4): struct.pack('<I', pawn),
            (pawn_instance + profile.ENTITY_IDENTITY, 8): struct.pack('<Q', pawn_identity),
            (pawn_instance, 8): struct.pack('<Q', base + profile.PLAYER_PAWN_VTABLE),
        })
        monitor = SimpleNamespace(base=base, memory=Mock(), _owned=Mock(), close=Mock())
        monitor.memory.read.side_effect = lambda address, size: fields[(address, size)]
        players = [{'handle': 0x10002, 'entity_index': 2},
                   {'handle': pawn, 'entity_index': 76, 'model_path': 'models/heroes/ivy/ivy.vmdl'}]
        return monitor, fields, players, controller

    def test_controller_id_resolves_exact_pawn_instead_of_roster_index(self):
        monitor, fields, players, _ = self.memory_fixture()
        self.assertEqual(resolve_player(monitor, 1, players), dict(handle=0x1004c, entity_index=76, controller_handle=0x10001))
        self.assertEqual(monitor._owned.call_count, 2)

    def test_recycled_controller_is_refused(self):
        monitor, fields, players, controller = self.memory_fixture()
        fields[(controller, 8)] = struct.pack('<Q', monitor.base + 1234)
        with self.assertRaisesRegex(RuntimeError, 'controller changed'):
            resolve_player(monitor, 1, players)

    def test_current_pawn_ignores_stale_truncated_or_duplicate_picker_roster(self):
        for roster in ([], [{'handle':0x2004c,'entity_index':76}],
                       [{'handle':0x20000+i,'entity_index':i} for i in range(16)],
                       [{'handle':0x1004c,'entity_index':76}]*2):
            monitor, _, _, _ = self.memory_fixture()
            with self.subTest(roster=roster):
                self.assertEqual(resolve_player(monitor,1,roster),dict(handle=0x1004c,entity_index=76,controller_handle=0x10001))

    def test_changed_identity_during_read_is_refused(self):
        monitor, fields, players, controller = self.memory_fixture()
        seen = set()
        def read(address, size):
            key = address, size
            if key in seen and address == controller:
                return struct.pack('<Q', 0)
            seen.add(key)
            return fields[key]
        monitor.memory.read.side_effect = read
        with self.assertRaisesRegex(RuntimeError, 'changed during'):
            resolve_player(monitor, 1, players)

    def pose_fixture(self):
        monitor,values,players,_=self.memory_fixture()
        player=players[1];pawn,node=0xc0000,0xd0000
        identity=0x80000+profile.IDENTITY_STRIDE*76
        offsets=dict(scene_node=816,owner=32,player_origin=96,player_angles=112,eye_offset=512,eye_angles=600)
        view=bytearray(36);struct.pack_into('<f',view,32,64.)
        values.update({(identity,8):struct.pack('<Q',pawn),
                       (identity+profile.IDENTITY_HANDLE,4):struct.pack('<I',player['handle']),
                       (pawn+profile.ENTITY_IDENTITY,8):struct.pack('<Q',identity),
                       (pawn,8):struct.pack('<Q',monitor.base+profile.PLAYER_PAWN_VTABLE),
                       (pawn+offsets['scene_node'],8):struct.pack('<Q',node),
                       (node+offsets['owner'],8):struct.pack('<Q',pawn),
                       (node+offsets['player_origin'],12):struct.pack('<3f',100,200,30),
                       (node+offsets['player_angles'],12):struct.pack('<3f',0,90,0),
                       (pawn+offsets['eye_angles'],12):struct.pack('<3f',0,90,0),
                       (pawn+offsets['eye_offset'],36):bytes(view)})
        return monitor,values,player,offsets,pawn,node

    def test_pose_is_near_correct_player_and_keeps_roll_and_aspect(self):
        monitor,_,player,offsets,_,_=self.pose_fixture()
        pose=player_freecam_pose(monitor,player,offsets,[0,0,0,0,0,7,1.5])
        self.assertAlmostEqual(pose['x'],100)
        self.assertAlmostEqual(pose['y'],40)
        self.assertAlmostEqual(pose['z'],118)
        self.assertEqual((pose['yaw'],pose['roll'],pose['aspect_ratio']),(90,7,1.5))

    def test_bad_pose_scene_owner_or_recycled_pawn_are_refused(self):
        for problem in ('owner','serial','nan'):
            monitor,values,player,offsets,pawn,node=self.pose_fixture()
            if problem=='owner':values[(node+offsets['owner'],8)]=struct.pack('<Q',pawn+8)
            if problem=='serial':values[(0x80000+profile.IDENTITY_STRIDE*76+profile.IDENTITY_HANDLE,4)]=struct.pack('<I',0x2004c)
            if problem=='nan':values[(node+offsets['player_origin'],12)]=struct.pack('<3f',float('nan'),0,0)
            with self.subTest(problem=problem),self.assertRaises(RuntimeError):
                player_freecam_pose(monitor,player,offsets,[0,0,0,0,0,0,1.5])

    def test_changed_position_during_sample_is_refused(self):
        monitor,values,player,offsets,_,node=self.pose_fixture()
        address=node+offsets['player_origin'];seen=False
        def read(addr,size):
            nonlocal seen
            if addr==address:
                if seen:return struct.pack('<3f',110,200,30)
                seen=True
            return values[(addr,size)]
        monitor.memory.read.side_effect=read
        with self.assertRaisesRegex(ReplayPlayerPoseChanged,'moved during') as error:
            player_freecam_pose(monitor,player,offsets,[0,0,0,0,0,0,1.5])
        self.assertEqual(error.exception.changes['player_origin']['before'],[100,200,30])
        self.assertEqual(error.exception.changes['player_origin']['after'],[110,200,30])

    def test_focus_moves_native_freecam_without_follow_or_replay_commands(self):
        controller = Mock()
        controller._op_lock = threading.RLock()
        controller._follow_settings = FollowSettings(250, 24, 8)
        controller._recorder_active.return_value=False
        controller._native_bridge.return_value.status.return_value = {'paused': True,'tick':100,'applied_pose':[0,0,0,0,0,0,1.5]}
        controller._native_bridge.return_value.editor_roster.return_value = {'players': []}
        player = {'handle': 0x1004c, 'entity_index': 76, 'controller_handle':0x10001}
        pose={'x':10.,'y':20.,'z':30.,'pitch':5.,'yaw':90.,'roll':0.,'aspect_ratio':1.5}
        with patch('dolly.replay_player_focus.FollowTargetMonitor') as factory, \
                patch('dolly.replay_player_focus.resolve_player', return_value=player), \
                patch('dolly.replay_player_focus._verify_pose_structure'), \
                patch('dolly.replay_player_focus.player_freecam_pose',create=True,return_value=pose):
            focus_replay_player(controller, 1)
            factory.return_value.close.assert_called_once()
        controller.enter_native_flight.assert_called_once_with(pose=pose,owner='panel')
        controller.start_selected_game_follow.assert_not_called()
        controller._request.assert_not_called()

    def test_real_freecam_handoff_keeps_replay_tick_and_never_retargets_game(self):
        from tests.test_native_flight_controller import configured_controller
        c,console,bridge=configured_controller()
        bridge.state='armed'
        bridge.require_capability=Mock()
        player={'handle':0x1004c,'entity_index':76,'controller_handle':0x10001}
        bridge.editor_roster=Mock(return_value={'players':[player]})
        saved_tick=console.tick
        pose=dict(x=100.,y=200.,z=90.,pitch=8.,yaw=90.,roll=0.,aspect_ratio=1.5)
        with patch('dolly.replay_player_focus.FollowTargetMonitor'), \
                patch('dolly.replay_player_focus.resolve_player',return_value=player), \
                patch('dolly.replay_player_focus._verify_pose_structure'), \
                patch('dolly.replay_player_focus.player_freecam_pose',return_value=pose):
            focus_replay_player(c,1,{})
        self.assertEqual(console.tick,saved_tick)
        self.assertTrue(console.paused)
        self.assertTrue(c._native_manual)
        self.assertEqual(bridge.pose,[100,200,90,8,90,0,1.5])
        self.assertFalse(any(str(command).startswith(('spec_target','demo_resume','demo_gototick','playdemo')) for command in console.events))
        self.assertFalse(c._follow_active)

    def live_fixture(self):
        from tests.test_native_flight_controller import configured_controller
        c, console, bridge = configured_controller()
        bridge.state = 'armed'
        bridge.require_capability = Mock()
        bridge.editor_roster = Mock(side_effect=AssertionError('Focus must not depend on picker roster'))
        monitor, values, player, offsets, pawn, node = self.pose_fixture()
        return c, console, bridge, monitor, values, player, offsets, pawn, node

    def assert_camera_unchanged(self, console, bridge, original):
        self.assertEqual(bridge.pose, original)
        self.assertFalse(any(str(event).startswith(('native.flight','native.hold','native.release',
            'spec_target','demo_resume','demo_gototick','playdemo')) for event in console.events))

    def test_real_controller_direct_pawn_handoff_needs_no_picker_roster(self):
        c, console, bridge, monitor, _, _, offsets, _, _ = self.live_fixture()
        tick = console.tick
        with patch('dolly.replay_player_focus.FollowTargetMonitor', return_value=monitor):
            focus_replay_player(c, 1, offsets)
        self.assertEqual(console.tick, tick)
        self.assertTrue(console.paused)
        for observed, expected in zip(bridge.pose[:3], [100, 40, 118]):
            self.assertAlmostEqual(observed, expected)
        self.assertEqual(bridge.last_start_owner, 'panel')
        self.assertEqual(c._freecam_player_evidence['handle'], 0x1004c)
        bridge.editor_roster.assert_not_called()
        monitor.close.assert_called_once()

    def test_direct_focus_keeps_existing_player_and_familiar_clone_admission(self):
        for vtable in (profile.PLAYER_PAWN_VTABLE,profile.FAMILIAR_CLONE_PAWN_VTABLE):
            c, console, bridge, monitor, values, _, offsets, pawn, _ = self.live_fixture()
            values[(pawn,8)] = struct.pack('<Q',monitor.base+vtable)
            with self.subTest(vtable=vtable), patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor):
                focus_replay_player(c,1,offsets)
            self.assertTrue(console.paused)
            self.assertEqual(bridge.last_start_owner,'panel')

    def test_absent_pawn_or_scene_is_typed_and_never_moves_camera(self):
        for problem in ('no_pawn','dead_handle','unspawned_handle','no_instance','observer','no_scene'):
            c, console, bridge, monitor, values, _, offsets, pawn, _ = self.live_fixture()
            if problem in ('no_pawn','dead_handle','unspawned_handle'):
                values[(0xa0000+profile.CONTROLLER_PAWN,4)] = struct.pack('<I',
                    {'no_pawn':0,'dead_handle':0xffffffff,'unspawned_handle':0xfffffffe}[problem])
            elif problem == 'no_instance':
                values[(0x80000+profile.IDENTITY_STRIDE*76,8)] = struct.pack('<Q',0)
            elif problem == 'observer':
                values[(pawn,8)] = struct.pack('<Q',monitor.base+profile.OBSERVER_PAWN_VTABLE)
            else:
                values[(pawn+offsets['scene_node'],8)] = struct.pack('<Q',0)
            original = list(bridge.pose)
            with self.subTest(problem=problem), patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                    self.assertRaisesRegex(ReplayPlayerUnavailable, 'Camera unchanged'):
                focus_replay_player(c,1,offsets)
            self.assert_camera_unchanged(console,bridge,original)
            monitor.close.assert_called_once()

    def test_recycled_pawn_controller_or_scene_integrity_errors_remain_visible(self):
        for problem in ('serial','controller_backlink','pawn_backlink','vtable','owner','fields','nan'):
            c, console, bridge, monitor, values, _, offsets, pawn, node = self.live_fixture()
            if problem == 'serial':
                values[(0x80000+profile.IDENTITY_STRIDE*76+profile.IDENTITY_HANDLE,4)] = struct.pack('<I',0x2004c)
            elif problem == 'controller_backlink':
                values[(0xa0000+profile.ENTITY_IDENTITY,8)] = struct.pack('<Q',0)
            elif problem == 'pawn_backlink':
                values[(pawn+profile.ENTITY_IDENTITY,8)] = struct.pack('<Q',0)
            elif problem == 'vtable':
                values[(pawn,8)] = struct.pack('<Q',monitor.base+1234)
            elif problem == 'owner':
                values[(node+offsets['owner'],8)] = struct.pack('<Q',pawn+8)
            elif problem == 'fields':
                offsets = {}
            else:
                values[(node+offsets['player_origin'],12)] = struct.pack('<3f',float('nan'),0,0)
            original = list(bridge.pose)
            with self.subTest(problem=problem), patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor):
                with self.assertRaises(RuntimeError) as error:
                    focus_replay_player(c,1,offsets)
                self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
            self.assert_camera_unchanged(console,bridge,original)

    def test_ownership_loss_is_not_a_quiet_missing_pawn(self):
        c, console, bridge, monitor, values, _, offsets, _, _ = self.live_fixture()
        values[(0xa0000+profile.CONTROLLER_PAWN,4)] = struct.pack('<I',0xffffffff)
        monitor._owned.side_effect = [None, RuntimeError('Owned process changed')]
        original = list(bridge.pose)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor):
            with self.assertRaisesRegex(RuntimeError,'Owned process changed') as error:
                focus_replay_player(c,1,offsets)
        self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
        self.assert_camera_unchanged(console,bridge,original)

    def test_missing_pawn_identity_change_is_not_quiet(self):
        c, console, bridge, monitor, values, _, offsets, _, _ = self.live_fixture()
        values[(0xa0000+profile.CONTROLLER_PAWN,4)] = struct.pack('<I',0xffffffff)
        original_read = monitor.memory.read.side_effect
        seen = False
        def read(address,size):
            nonlocal seen
            if address == 0xa0000+profile.CONTROLLER_PAWN:
                if seen: return struct.pack('<I',0x1004c)
                seen = True
            return original_read(address,size)
        monitor.memory.read.side_effect = read
        original = list(bridge.pose)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor):
            with self.assertRaisesRegex(RuntimeError,'changed during') as error:
                focus_replay_player(c,1,offsets)
        self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
        self.assert_camera_unchanged(console,bridge,original)

    def test_changed_tick_after_sample_blocks_handoff(self):
        c, console, bridge, monitor, _, _, offsets, _, _ = self.live_fixture()
        original = list(bridge.pose)
        def sample(*args,**kwargs):
            pose = player_freecam_pose(*args,**kwargs)
            console.tick += 1
            return pose
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.player_freecam_pose',side_effect=sample), \
                self.assertRaisesRegex(RuntimeError,'replay changed'):
            focus_replay_player(c,1,offsets)
        self.assert_camera_unchanged(console,bridge,original)

    def test_target_disappearing_after_pose_sample_is_not_a_quiet_absence(self):
        c, console, bridge, monitor, values, _, offsets, _, _ = self.live_fixture()
        original = list(bridge.pose)
        def sample(*args,**kwargs):
            pose = player_freecam_pose(*args,**kwargs)
            values[(0xa0000+profile.CONTROLLER_PAWN,4)] = struct.pack('<I',0xffffffff)
            return pose
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.player_freecam_pose',side_effect=sample):
            with self.assertRaisesRegex(RuntimeError,'changed during') as error:
                focus_replay_player(c,1,offsets)
        self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
        self.assert_camera_unchanged(console,bridge,original)

    def test_controller_serial_change_between_samples_is_rejected(self):
        c, console, bridge, monitor, values, _, offsets, _, _ = self.live_fixture()
        original = list(bridge.pose)
        def sample(*args,**kwargs):
            pose = player_freecam_pose(*args,**kwargs)
            values[(0x80000+profile.IDENTITY_STRIDE+profile.IDENTITY_HANDLE,4)] = struct.pack('<I',0x20001)
            return pose
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.player_freecam_pose',side_effect=sample):
            with self.assertRaisesRegex(RuntimeError,'player or replay changed') as error:
                focus_replay_player(c,1,offsets)
        self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
        self.assert_camera_unchanged(console,bridge,original)

    def test_tick_change_during_absent_target_sampling_remains_visible(self):
        c, console, bridge, monitor, values, _, offsets, _, _ = self.live_fixture()
        values[(0xa0000+profile.CONTROLLER_PAWN,4)] = struct.pack('<I',0xffffffff)
        original_read = monitor.memory.read.side_effect
        changed = False
        def read(address,size):
            nonlocal changed
            if address == 0xa0000+profile.CONTROLLER_PAWN and not changed:
                console.tick += 1
                changed = True
            return original_read(address,size)
        monitor.memory.read.side_effect = read
        original = list(bridge.pose)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor):
            with self.assertRaisesRegex(RuntimeError,'replay changed') as error:
                focus_replay_player(c,1,offsets)
        self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
        self.assert_camera_unchanged(console,bridge,original)

    def test_changed_native_replay_identity_is_rejected_before_target_sampling(self):
        c, console, bridge, _, _, _, offsets, _, _ = self.live_fixture()
        original = list(bridge.pose)
        actual_status = bridge.status
        def status():
            return dict(actual_status(),demo_name='different.dem')
        with patch.object(bridge,'status',side_effect=status), \
                patch('dolly.replay_player_focus.FollowTargetMonitor') as factory, \
                self.assertRaisesRegex(RuntimeError,'replay identity changed'):
            focus_replay_player(c,1,offsets)
        factory.assert_not_called()
        self.assert_camera_unchanged(console,bridge,original)

    def test_recording_or_running_replay_never_samples_or_moves_camera(self):
        for recording in (False,True):
            c, console, bridge, _, _, _, offsets, _, _ = self.live_fixture()
            console.paused = recording
            original = list(bridge.pose)
            with self.subTest(recording=recording), patch.object(c,'_recorder_active',return_value=recording), \
                    patch('dolly.replay_player_focus.FollowTargetMonitor') as factory, \
                    self.assertRaisesRegex(RuntimeError,'Pause the replay'):
                focus_replay_player(c,1,offsets)
            factory.assert_not_called()
            self.assert_camera_unchanged(console,bridge,original)

    def test_focus_logs_identifiers_tick_and_rejection_stage(self):
        c, _, _, monitor, values, _, offsets, _, _ = self.live_fixture()
        values[(0xa0000+profile.CONTROLLER_PAWN,4)] = struct.pack('<I',0xffffffff)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                self.assertLogs('dolly.replay_player_focus',level='INFO') as logs, \
                self.assertRaises(ReplayPlayerUnavailable):
            focus_replay_player(c,1,offsets)
        text = '\n'.join(logs.output)
        for expected in ("'player_id': 1", "'tick':", "'stage': 'pawn_identity'",
                         "'controller_handle': 65537", "'pawn_handle': 4294967295", "'reason':"):
            self.assertIn(expected,text)

    def mutate_pose_field(self, monitor, values, offsets, pawn, node, field, *, persistent=False, changed=None):
        address=(node if field.startswith('player_') else pawn)+offsets[field]
        size=36 if field=='eye_offset' else 12
        original_read=monitor.memory.read.side_effect
        original=values[(address,size)]
        component=32 if field=='eye_offset' else 0
        count=0
        def read(addr,length):
            nonlocal count
            if addr==address and length==size:
                count+=1
                if count>=2:
                    raw=bytearray(original)
                    delta=count if persistent else 1
                    struct.pack_into('<f',raw,component,struct.unpack_from('<f',original,component)[0]+delta)
                    if changed is not None: changed(count,addr,length)
                    return bytes(raw)
            return original_read(addr,length)
        monitor.memory.read.side_effect=read

    def test_each_mutable_pose_field_can_settle_on_a_fresh_second_sample(self):
        for field in ('player_origin','player_angles','eye_angles','eye_offset'):
            c, console, bridge, monitor, values, player, offsets, pawn, node=self.live_fixture()
            self.mutate_pose_field(monitor,values,offsets,pawn,node,field)
            tick=console.tick
            with self.subTest(field=field), patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                    patch('dolly.replay_player_focus.player_freecam_pose',wraps=player_freecam_pose) as sample, \
                    self.assertLogs('dolly.replay_player_focus',level='INFO') as logs:
                focus_replay_player(c,1,offsets)
            self.assertEqual(sample.call_count,2)
            self.assertEqual(console.tick,tick)
            self.assertTrue(console.paused)
            self.assertEqual(console.events.count('native.flight'),1)
            expected=player_freecam_pose(monitor,player,offsets,bridge.pose)
            for value,key in zip(bridge.pose,('x','y','z','pitch','yaw','roll','aspect_ratio')):
                self.assertAlmostEqual(value,expected[key])
            text='\n'.join(logs.output)
            for marker in (field,"'before':","'after':","'attempt': 1","'attempt': 2"):
                self.assertIn(marker,text)

    def test_persistent_mutable_settling_is_distinct_bounded_and_never_hands_off(self):
        c, console, bridge, monitor, values, _, offsets, pawn, node=self.live_fixture()
        self.mutate_pose_field(monitor,values,offsets,pawn,node,'player_origin',persistent=True)
        original=list(bridge.pose)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.player_freecam_pose',wraps=player_freecam_pose) as sample, \
                self.assertLogs('dolly.replay_player_focus',level='INFO') as logs:
            with self.assertRaisesRegex(ReplayPlayerDeferred,'still settling') as error:
                focus_replay_player(c,1,offsets)
        self.assertNotIsInstance(error.exception,ReplayPlayerUnavailable)
        self.assertEqual(POSE_SAMPLE_ATTEMPTS,3)
        self.assertEqual(sample.call_count,3)
        self.assert_camera_unchanged(console,bridge,original)
        self.assertIn("'attempt': 3",'\n'.join(logs.output))
        self.assertIn('Replay player focus deferred','\n'.join(logs.output))

    def test_mutable_change_never_retries_structural_read_identity_or_session_failures(self):
        for problem in ('mixed_owner','pawn_serial','controller_serial','tick','pause','recording','ownership','cancel','read','nan'):
            c, console, bridge, monitor, values, _, offsets, pawn, node=self.live_fixture()
            c._recorder_active=Mock(return_value=False)
            def changed(count,addr,length):
                if count!=2:return
                if problem=='mixed_owner':values[(node+offsets['owner'],8)]=struct.pack('<Q',pawn+8)
                elif problem=='pawn_serial':values[(0x80000+profile.IDENTITY_STRIDE*76+profile.IDENTITY_HANDLE,4)]=struct.pack('<I',0x2004c)
                elif problem=='controller_serial':values[(0x80000+profile.IDENTITY_STRIDE+profile.IDENTITY_HANDLE,4)]=struct.pack('<I',0x20001)
                elif problem=='tick':console.tick+=1
                elif problem=='pause':console.paused=False
                elif problem=='recording':c._recorder_active.return_value=True
                elif problem=='ownership':monitor._owned.side_effect=RuntimeError('Owned process changed')
                elif problem=='cancel':c._paused_cancelled=lambda:True
                elif problem=='read':raise OSError('Unreadable mutable sample')
                elif problem=='nan':
                    # Fail a later mutable region after origin was observed changing.
                    values[(pawn+offsets['eye_angles'],12)]=struct.pack('<3f',float('nan'),0,0)
            self.mutate_pose_field(monitor,values,offsets,pawn,node,'player_origin',persistent=True,changed=changed)
            original=list(bridge.pose)
            with self.subTest(problem=problem), patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                    patch('dolly.replay_player_focus.player_freecam_pose',wraps=player_freecam_pose) as sample:
                with self.assertRaises((RuntimeError,OSError)) as error:
                    focus_replay_player(c,1,offsets)
                self.assertNotIsInstance(error.exception,(ReplayPlayerDeferred,ReplayPlayerUnavailable,ReplayPlayerPoseChanged))
            self.assertEqual(sample.call_count,1)
            self.assert_camera_unchanged(console,bridge,original)

    def test_final_attempt_integrity_loss_cannot_be_classified_as_deferred(self):
        for problem in ('controller_serial','tick','ownership','cancel'):
            c, console, bridge, monitor, values, _, offsets, pawn, node=self.live_fixture()
            def changed(count,addr,length):
                if count!=6:return
                if problem=='controller_serial':values[(0x80000+profile.IDENTITY_STRIDE+profile.IDENTITY_HANDLE,4)]=struct.pack('<I',0x20001)
                elif problem=='tick':console.tick+=1
                elif problem=='ownership':monitor._owned.side_effect=RuntimeError('Owned process changed')
                else:c._paused_cancelled=lambda:True
            self.mutate_pose_field(monitor,values,offsets,pawn,node,'player_origin',persistent=True,changed=changed)
            original=list(bridge.pose)
            with self.subTest(problem=problem), patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                    patch('dolly.replay_player_focus.player_freecam_pose',wraps=player_freecam_pose) as sample:
                with self.assertRaises(RuntimeError) as error:
                    focus_replay_player(c,1,offsets)
                self.assertNotIsInstance(error.exception,(ReplayPlayerDeferred,ReplayPlayerUnavailable,ReplayPlayerPoseChanged))
            self.assertEqual(sample.call_count,3)
            self.assert_camera_unchanged(console,bridge,original)

    def test_structural_scene_change_after_mutable_sample_prevents_retry(self):
        c, console, bridge, monitor, values, _, offsets, pawn, node=self.live_fixture()
        self.mutate_pose_field(monitor,values,offsets,pawn,node,'player_origin')
        calls=0
        def sample(*args,**kwargs):
            nonlocal calls
            calls+=1
            try:return player_freecam_pose(*args,**kwargs)
            except ReplayPlayerPoseChanged:
                next_node=node+0x1000
                for field,size in (('owner',8),('player_origin',12),('player_angles',12)):
                    values[(next_node+offsets[field],size)]=values[(node+offsets[field],size)]
                values[(pawn+offsets['scene_node'],8)]=struct.pack('<Q',next_node)
                raise
        original=list(bridge.pose)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.player_freecam_pose',side_effect=sample), \
                self.assertRaisesRegex(RuntimeError,'identity changed during'):
            focus_replay_player(c,1,offsets)
        self.assertEqual(calls,1)
        self.assert_camera_unchanged(console,bridge,original)

    def test_final_structural_snapshot_blocks_success_and_deferred_after_context_check(self):
        for result in ('success','deferred'):
            for field in ('entity_system','pawn_chunk','pawn_instance','pawn_handle',
                          'pawn_backpointer','pawn_vtable','scene_node','scene_owner'):
                c, console, bridge, monitor, values, _, offsets, pawn, node=self.live_fixture()
                identity=0x80000+profile.IDENTITY_STRIDE*76
                locations={
                    'entity_system':(monitor.base+profile.ENTITY_LIST,8),
                    'pawn_chunk':(0x60000,8),
                    'pawn_instance':(identity,8),
                    'pawn_handle':(identity+profile.IDENTITY_HANDLE,4),
                    'pawn_backpointer':(pawn+profile.ENTITY_IDENTITY,8),
                    'pawn_vtable':(pawn,8),
                    'scene_node':(pawn+offsets['scene_node'],8),
                    'scene_owner':(node+offsets['owner'],8),
                }
                if result=='deferred':
                    self.mutate_pose_field(monitor,values,offsets,pawn,node,'player_origin',persistent=True)
                calls=0;check_pending=False
                def sample(*args,**kwargs):
                    nonlocal calls,check_pending
                    calls+=1
                    try:
                        pose=player_freecam_pose(*args,**kwargs)
                    except ReplayPlayerPoseChanged:
                        check_pending=calls==POSE_SAMPLE_ATTEMPTS
                        raise
                    check_pending=True
                    return pose
                original_status=bridge.status
                def status():
                    nonlocal check_pending
                    state=original_status()
                    if check_pending:
                        check_pending=False
                        key=locations[field]
                        value=int.from_bytes(values[key],'little')+1
                        values[key]=value.to_bytes(key[1],'little')
                    return state
                original=list(bridge.pose)
                with self.subTest(result=result,field=field), \
                        patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                        patch('dolly.replay_player_focus.player_freecam_pose',side_effect=sample), \
                        patch.object(bridge,'status',side_effect=status), \
                        self.assertRaisesRegex(RuntimeError,'identity changed during') as error:
                    focus_replay_player(c,1,offsets)
                self.assertNotIsInstance(error.exception,(ReplayPlayerDeferred,ReplayPlayerUnavailable,ReplayPlayerPoseChanged))
                self.assertEqual(calls,1 if result=='success' else POSE_SAMPLE_ATTEMPTS)
                self.assert_camera_unchanged(console,bridge,original)

    def test_scene_identity_must_also_match_between_fresh_attempts(self):
        c, console, bridge, monitor, values, _, offsets, pawn, node=self.live_fixture()
        self.mutate_pose_field(monitor,values,offsets,pawn,node,'player_origin')
        def after_checked_attempt(message,*args):
            if message.startswith('Replay player focus mutable sample changed:'):
                next_node=node+0x1000
                for field,size in (('owner',8),('player_origin',12),('player_angles',12)):
                    values[(next_node+offsets[field],size)]=values[(node+offsets[field],size)]
                values[(pawn+offsets['scene_node'],8)]=struct.pack('<Q',next_node)
        original=list(bridge.pose)
        with patch('dolly.replay_player_focus.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.player_freecam_pose',wraps=player_freecam_pose) as sample, \
                patch('dolly.replay_player_focus.LOG.info',side_effect=after_checked_attempt), \
                self.assertRaisesRegex(RuntimeError,'scene changed between'):
            focus_replay_player(c,1,offsets)
        self.assertEqual(sample.call_count,2)
        self.assert_camera_unchanged(console,bridge,original)

    def dispatch_queue_fixture(self):
        from dolly.gui import DollyApp
        from dolly.ui.operations import OperationQueue
        from tests.test_editor_session import EditorSessionTests, Value
        fixture = EditorSessionTests()
        fixture.setUp()
        app = fixture.app
        app.native_editor_active = True
        app._replay_events_cache = KillIndex(2,10000,(),((1,'Ivy player'),))
        app._replay_event_reader = Mock()
        app._replay_event_reader.snapshot.return_value = app._replay_events_cache
        app.preview_attach = False
        app.status_text, app.busy_text = Value('Ready'), Value('')
        app.operations = OperationQueue()
        app._submit = MethodType(DollyApp._submit,app)
        return app, fixture.bridge

    def test_unavailable_focus_uses_real_done_callback_and_native_footer_without_popup(self):
        from dolly.gui import DollyApp
        from dolly.editor_publication import configure
        app, bridge = self.dispatch_queue_fixture()
        notice = 'This player has no hero at this tick. Camera unchanged.'
        def publish():
            configure(app)
            app.closed = True  # Stop the GUI poll after exercising its actual done/callback path.
        with patch.object(app.controller, 'follow_replay_player', side_effect=ReplayPlayerUnavailable(notice)):
            _dispatch(app,{'action':'focus_replay_player','value':1},bridge,publish=publish)
            app.operations.jobs.put(None)
            app.operations.run(lambda:'error')
        DollyApp._poll_once(app)
        self.assertEqual(app.status_text.get(),notice)
        self.assertEqual(bridge.configure_editor.call_args.kwargs['message'],notice)
        app._error.assert_not_called()
        self.assertEqual(app._replay_events_cache.players,((1,'Ivy player'),))

    def test_deferred_focus_uses_same_real_done_callback_and_native_footer(self):
        from dolly.gui import DollyApp
        from dolly.editor_publication import configure
        app, bridge = self.dispatch_queue_fixture()
        notice = "This player's view is still settling. Camera unchanged; try again."
        def publish():
            configure(app)
            app.closed=True
        with patch.object(app.controller, 'follow_replay_player', side_effect=ReplayPlayerDeferred(notice)):
            _dispatch(app,{'action':'focus_replay_player','value':1},bridge,publish=publish)
            app.operations.jobs.put(None)
            app.operations.run(lambda:'error')
        DollyApp._poll_once(app)
        self.assertEqual(app.status_text.get(),notice)
        self.assertEqual(bridge.configure_editor.call_args.kwargs['message'],notice)
        app._error.assert_not_called()

    def test_real_dispatch_worker_absence_keeps_pending_participant_without_target_writes(self):
        from dolly.gui import DollyApp
        from tests import test_follow_controller
        app, publication_bridge = self.dispatch_queue_fixture()
        fixture = SimpleNamespace(addCleanup=self.addCleanup)
        test_follow_controller.FollowControllerTests.setUp(fixture)
        c, console, bridge = fixture.c, fixture.console, fixture.bridge
        app.controller=c
        bridge.editor_roster = Mock(return_value={'players': []})
        monitor = Mock()
        original=list(bridge.original)
        published=[]
        def publish():
            published.append(app.status_text.get())
            app.closed=True
        with patch('dolly.follow_target.FollowTargetMonitor',return_value=monitor), \
                patch('dolly.replay_player_focus.resolve_participant', side_effect=ReplayPlayerUnavailable('no hero')) as resolve:
            _dispatch(app,{'action':'focus_replay_player','value':1},bridge,publish=publish)
            app.operations.jobs.put(None)
            app.operations.run(lambda:'error')
        DollyApp._poll_once(app)
        self.assertIn('Follow is waiting',app.status_text.get())
        self.assertEqual(published,[app.status_text.get()])
        self.assertEqual(bridge.pose, original)
        self.assertEqual(c._participant_follow['identifier'], 1)
        self.assertFalse(c._follow_active)
        self.assertFalse(any(event.startswith('spec_target ') for event in console.events))
        self.assertEqual(resolve.call_count, 6)
        app._error.assert_not_called()
        self.assertIsNone(getattr(c,'_freecam_player_evidence',None))

    def test_unexpected_focus_error_still_reaches_real_operation_error_channel(self):
        app, bridge = self.dispatch_queue_fixture()
        with patch.object(app.controller, 'follow_replay_player', side_effect=RuntimeError('Integrity check failed')):
            _dispatch(app,{'action':'focus_replay_player','value':1},bridge,publish=lambda:None)
            app.operations.jobs.put(None)
            with self.assertLogs('dolly',level='ERROR'):
                app.operations.run(lambda:'error')
        event, label, error = app.operations.events.get_nowait()
        self.assertEqual(event,'error')
        self.assertIsInstance(error,RuntimeError)
        self.assertNotIsInstance(error,ReplayPlayerUnavailable)
        self.assertEqual(app.status_text.get(),'Ready')

    def test_unavailable_type_is_not_silenced_for_other_actions(self):
        for error_type in (ReplayPlayerUnavailable,ReplayPlayerDeferred):
            app, bridge = self.dispatch_queue_fixture()
            app.controller.destroy_ragdolls.side_effect = error_type('unexpected here')
            _dispatch(app,{'action':'destroy_ragdolls','value':0},bridge,publish=lambda:None)
            app.operations.jobs.put(None)
            with self.subTest(error_type=error_type),self.assertLogs('dolly',level='ERROR'):
                app.operations.run(lambda:'error')
            self.assertEqual(app.operations.events.get_nowait()[0],'error')


if __name__ == '__main__':
    unittest.main()
