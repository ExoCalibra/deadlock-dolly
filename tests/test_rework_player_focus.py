import unittest
import struct
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dolly.editor_dispatch import _dispatch
from dolly.replay_events import KillIndex
from dolly.replay_player_focus import resolve_player, focus_replay_player, player_freecam_pose
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
            focus.assert_called_once_with(app.controller, 2, {})

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
        monitor = SimpleNamespace(base=base, memory=Mock(), _owned=Mock())
        monitor.memory.read.side_effect = lambda address, size: fields[(address, size)]
        players = [{'handle': 0x10002, 'entity_index': 2},
                   {'handle': pawn, 'entity_index': 76, 'model_path': 'models/heroes/ivy/ivy.vmdl'}]
        return monitor, fields, players, controller

    def test_controller_id_resolves_exact_pawn_instead_of_roster_index(self):
        monitor, fields, players, _ = self.memory_fixture()
        self.assertEqual(resolve_player(monitor, 1, players), players[1])
        self.assertEqual(monitor._owned.call_count, 2)

    def test_recycled_controller_and_missing_pawn_are_refused(self):
        monitor, fields, players, controller = self.memory_fixture()
        fields[(controller, 8)] = struct.pack('<Q', monitor.base + 1234)
        with self.assertRaisesRegex(RuntimeError, 'controller changed'):
            resolve_player(monitor, 1, players)
        monitor, fields, players, _ = self.memory_fixture()
        with self.assertRaisesRegex(RuntimeError, 'not available'):
            resolve_player(monitor, 1, players[:1])

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
        with self.assertRaisesRegex(RuntimeError, 'not available'):
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
        with self.assertRaisesRegex(RuntimeError,'moved during'):
            player_freecam_pose(monitor,player,offsets,[0,0,0,0,0,0,1.5])

    def test_focus_moves_native_freecam_without_follow_or_replay_commands(self):
        controller = Mock()
        controller._op_lock = threading.RLock()
        controller._follow_settings = FollowSettings(250, 24, 8)
        controller._recorder_active.return_value=False
        controller._native_bridge.return_value.status.return_value = {'paused': True,'tick':100,'applied_pose':[0,0,0,0,0,0,1.5]}
        controller._native_bridge.return_value.editor_roster.return_value = {'players': []}
        player = {'handle': 0x1004c, 'entity_index': 76}
        pose={'x':10.,'y':20.,'z':30.,'pitch':5.,'yaw':90.,'roll':0.,'aspect_ratio':1.5}
        with patch('dolly.replay_player_focus.FollowTargetMonitor') as factory, \
                patch('dolly.replay_player_focus.resolve_player', return_value=player), \
                patch('dolly.replay_player_focus.player_freecam_pose',create=True,return_value=pose):
            focus_replay_player(controller, 1)
            factory.return_value.close.assert_called_once()
        controller.enter_native_flight.assert_called_once_with(pose=pose,owner='panel')
        controller.start_selected_game_follow.assert_not_called()
        controller._request.assert_not_called()

    def test_real_freecam_handoff_keeps_replay_tick_and_never_retargets_game(self):
        from tests.test_native_flight_controller import configured_controller
        c,console,bridge=configured_controller()
        bridge.require_capability=Mock()
        player={'handle':0x1004c,'entity_index':76}
        bridge.editor_roster=Mock(return_value={'players':[player]})
        saved_tick=console.tick
        pose=dict(x=100.,y=200.,z=90.,pitch=8.,yaw=90.,roll=0.,aspect_ratio=1.5)
        with patch('dolly.replay_player_focus.FollowTargetMonitor'), \
                patch('dolly.replay_player_focus.resolve_player',return_value=player), \
                patch('dolly.replay_player_focus.player_freecam_pose',return_value=pose):
            focus_replay_player(c,1,{})
        self.assertEqual(console.tick,saved_tick)
        self.assertTrue(console.paused)
        self.assertTrue(c._native_manual)
        self.assertEqual(bridge.pose,[100,200,90,8,90,0,1.5])
        self.assertFalse(any(str(command).startswith(('spec_target','demo_resume','demo_gototick','playdemo')) for command in console.events))
        self.assertFalse(c._follow_active)


if __name__ == '__main__':
    unittest.main()
