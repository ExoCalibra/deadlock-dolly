import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, call, patch

from dolly.follow_target import FollowTargetMonitor, HEALTH_CONTEXT_SPANS
from dolly._runtime_generated import FollowTarget as G
from dolly.preload import PreloadError


class FollowTargetTests(unittest.TestCase):
    def health_fixture(self):
        m, blocks, chunk, services, target = self.fixture()
        m._client_data = b'fixture'
        for rva, size in HEALTH_CONTEXT_SPANS:
            blocks[m.base + rva] = b'\x90' * size
        def put(address, value, fmt='<Q'):
            blocks[address] = struct.pack(fmt, value)
        controller, pawn, hero_controller = 0x30000, 0x40000, 0x70000
        put(controller + G.NETWORK_STATE, 1, '<B')
        put(pawn + G.NETWORK_STATE, 1, '<B')
        for vtable, slot, getter in ((G.OBSERVER_PAWN_VTABLE, G.OBSERVER_PREDICATE_SLOT, G.OBSERVER_PREDICATE),
                                    (G.PLAYER_PAWN_VTABLE, G.PLAYER_PREDICATE_SLOT, G.PLAYER_PREDICATE),
                                    (G.PLAYER_PAWN_VTABLE, G.PLAYER_DATA_PREDICATE_SLOT, G.PLAYER_DATA_PREDICATE),
                                    (G.CONTROLLER_VTABLE, G.CONTROLLER_PREDICATE_SLOT, G.CONTROLLER_PREDICATE)):
            put(m.base + vtable + slot, m.base + getter)
        put(target + G.PAWN_CONTROLLER, 0x18003, '<I')
        identity = chunk + G.IDENTITY_STRIDE * 3
        put(identity, hero_controller)
        put(identity + G.IDENTITY_HANDLE, 0x18003, '<I')
        put(hero_controller + G.IDENTITY_HANDLE, identity)
        put(hero_controller, m.base + G.CONTROLLER_VTABLE)
        put(hero_controller + G.CONTROLLER_FINAL_DATA, m.base + G.CONTROLLER_FINAL_VTABLE)
        code = patch('dolly.follow_target._image_bytes', side_effect=lambda data, rva, size: b'\x90' * size)
        code.start()
        self.addCleanup(code.stop)
        camera = patch('dolly.follow_target.ReplayCameraMonitor.sample',
                       return_value={'coherent': True, 'ready': True})
        camera.start()
        self.addCleanup(camera.stop)
        return m, blocks, services, target, hero_controller

    def test_health_reveal_requires_typed_selected_controller_receiver(self):
        m, *_ = self.health_fixture()
        self.assertEqual(m.sample_health_hud_context()['handle'], 0x10002)

    def test_health_refuses_missing_recycled_or_wrong_player_data(self):
        for invalid in ('missing', 'recycled', 'receiver', 'base_constructor_type', 'controller_type', 'predicate'):
            with self.subTest(invalid=invalid):
                m, blocks, _, target, hero_controller = self.health_fixture()
                address, value, fmt = {
                    'missing': (target + G.PAWN_CONTROLLER, 0xffffffff, '<I'),
                    'recycled': (target + G.PAWN_CONTROLLER, 0x20003, '<I'),
                    'receiver': (hero_controller + G.CONTROLLER_FINAL_DATA, 0, '<Q'),
                    'base_constructor_type': (hero_controller + G.CONTROLLER_FINAL_DATA, m.base + 0x267c5f8, '<Q'),
                    'controller_type': (hero_controller, m.base + G.OBSERVER_PAWN_VTABLE, '<Q'),
                    'predicate': (m.base + G.CONTROLLER_VTABLE + G.CONTROLLER_PREDICATE_SLOT, m.base + G.PLAYER_DATA_PREDICATE, '<Q'),
                }[invalid]
                blocks[address] = struct.pack(fmt, value)
                with self.assertRaises(PreloadError):
                    m.sample_health_hud_context()

    def test_health_refuses_unreviewed_mode_and_playing_team_fallbacks(self):
        for address, value in ((0x30000 + G.NETWORK_STATE, 2), (0x40000 + G.NETWORK_STATE, 3),
                               (0x50000 + G.OBSERVER_MODE, 4)):
            m, blocks, *_ = self.health_fixture()
            blocks[address] = bytes([value])
            with self.assertRaises(PreloadError):
                m.sample_health_hud_context()

    def test_health_original_modes_need_valid_player_not_follow_chase(self):
        for mode in (0, 1, 2, 3):
            with self.subTest(mode=mode):
                m, blocks, services, *_ = self.health_fixture()
                blocks[services + G.OBSERVER_MODE] = bytes([mode])
                self.assertEqual(m.sample_health_hud_context()['mode'], mode)
                blocks[services + G.OBSERVER_TARGET] = struct.pack('<I', 0xffffffff)
                with self.assertRaises(PreloadError):
                    m.sample_health_hud_context()

    def test_selection_can_leave_unreviewed_mode_without_authorizing_reveal(self):
        m, blocks, _, services, _ = self.fixture()
        blocks[services + G.OBSERVER_MODE] = bytes([4])
        blocks[services + G.OBSERVER_TARGET] = struct.pack('<I', 0xffffffff)
        self.assertEqual(m.sample_selection_context(), {'observer_mode': 4, 'previous_target_handle': 0xffffffff})
        with self.assertRaises(PreloadError) as error:
            m.sample_target(require_chase=False)
        self.assertEqual(error.exception.observer_mode, 4)

    def test_selection_still_requires_reviewed_local_pawn(self):
        m, blocks, *_ = self.fixture()
        blocks[0x40000] = struct.pack('<Q', m.base + G.SERVICES_VTABLES[0])
        with self.assertRaises(PreloadError):
            m.sample_selection_context()

    def test_health_refuses_torn_receiver(self):
        m, blocks, _, _, hero_controller = self.health_fixture()
        address = hero_controller + G.CONTROLLER_FINAL_DATA
        read = m.memory.read.side_effect
        count = 0
        def changing_read(where, size):
            nonlocal count
            if where == address:
                count += 1
                if count > 1:
                    return struct.pack('<Q', 0)
            return read(where, size)
        m.memory.read.side_effect = changing_read
        with self.assertRaisesRegex(PreloadError, 'changed during'):
            m.sample_health_hud_context()

    def test_health_refuses_changed_code_or_unsettled_camera(self):
        m, blocks, *_ = self.health_fixture()
        rva, size = HEALTH_CONTEXT_SPANS[0]
        blocks[m.base + rva] = b'\x00' * size
        with self.assertRaisesRegex(PreloadError, 'code differs'):
            m.sample_health_hud_context()
        blocks[m.base + rva] = b'\x90' * size
        with patch('dolly.follow_target.ReplayCameraMonitor.sample', side_effect=[
                {'coherent': True, 'ready': True}, {'coherent': True, 'ready': False}]):
            with self.assertRaisesRegex(PreloadError, 'camera changed'):
                m.sample_health_hud_context()

    def fixture(self):
        m = FollowTargetMonitor.__new__(FollowTargetMonitor)
        m.base = 0x180000000
        m._owned = Mock()
        blocks = {}
        def put(address, value, fmt='<Q'):
            blocks[address] = struct.pack(fmt, value)
        system, chunk, controller, pawn, services, target = range(0x10000, 0x70000, 0x10000)
        put(m.base + G.ENTITY_LIST, system)
        put(system, chunk)
        put(m.base + G.CONTROLLER, controller)
        put(controller, m.base + G.CONTROLLER_VTABLE)
        put(controller + G.CONTROLLER_PAWN, 0x8001, '<I')
        for handle, instance, vt in ((0x8001, pawn, G.OBSERVER_PAWN_VTABLE), (0x10002, target, G.PLAYER_PAWN_VTABLE)):
            identity = chunk + G.IDENTITY_STRIDE * (handle & 0x1ff)
            put(identity, instance)
            put(identity + G.IDENTITY_HANDLE, handle, '<I')
            put(instance + G.IDENTITY_HANDLE, identity)
            put(instance, m.base + vt)
        put(pawn + G.OBSERVER_SERVICES_OFFSET, services)
        put(pawn + 0xe40, 0)  # Prior-build field was null in the 6745 failure.
        put(services, m.base + G.SERVICES_VTABLES[0])
        put(m.base + G.SERVICES_VTABLES[0] + G.OBSERVER_MODE_SLOT, m.base + G.GET_OBSERVER_MODE)
        put(m.base + G.SERVICES_VTABLES[0] + G.OBSERVER_TARGET_SLOT, m.base + G.GET_OBSERVER_TARGET)
        put(services + G.OBSERVER_MODE, 2, '<B')
        put(services + G.OBSERVER_TARGET, 0x10002, '<I')
        m.memory = Mock()
        m.memory.read.side_effect = lambda address, size: blocks[address][:size]
        return m, blocks, chunk, services, target

    def test_exact_full_handle(self):
        m, *_ = self.fixture()
        self.assertEqual(m.sample_target(), {'handle': 0x10002, 'entity_index': 2, 'mode': 2})
        self.assertEqual(m._owned.call_count, 2)

    def test_player_pawn_local_chain_is_accepted_for_follow(self):
        m, blocks, *_ = self.fixture()
        blocks[0x40000] = struct.pack('<Q', m.base + G.PLAYER_PAWN_VTABLE)
        self.assertEqual(m.sample_target()['handle'], 0x10002)

    def test_prior_services_field_cannot_rescue_missing_current_services(self):
        for pawn_vtable in (G.OBSERVER_PAWN_VTABLE, G.PLAYER_PAWN_VTABLE):
            with self.subTest(pawn_vtable=hex(pawn_vtable)):
                m, blocks, _, services, _ = self.fixture()
                blocks[0x40000] = struct.pack('<Q', m.base + pawn_vtable)
                blocks[0x40000 + 0xe40] = struct.pack('<Q', services)
                blocks[0x40000 + G.OBSERVER_SERVICES_OFFSET] = struct.pack('<Q', 0)
                with self.assertRaisesRegex(PreloadError, 'observer services.*got null'):
                    m.sample_selection_context()

    def test_services_pointer_change_during_selection_is_refused(self):
        m, blocks, *_ = self.fixture()
        address = 0x40000 + G.OBSERVER_SERVICES_OFFSET
        original_read = m.memory.read.side_effect
        reads = 0
        def changing_read(where, size):
            nonlocal reads
            if where == address:
                reads += 1
                if reads > 1:
                    return struct.pack('<Q', 0)
            return original_read(where, size)
        m.memory.read.side_effect = changing_read
        with self.assertRaisesRegex(PreloadError, 'changed during'):
            m.sample_selection_context()

    def test_familiar_clone_target_is_accepted_for_follow(self):
        m, blocks, *_ = self.fixture()
        blocks[0x60000] = struct.pack('<Q', m.base + G.FAMILIAR_CLONE_PAWN_VTABLE)
        self.assertEqual(m.sample_target()['handle'], 0x10002)

    def test_health_defers_when_local_pawn_is_a_player_pawn(self):
        m, blocks, *_ = self.health_fixture()
        blocks[0x40000] = struct.pack('<Q', m.base + G.PLAYER_PAWN_VTABLE)
        with self.assertRaisesRegex(PreloadError, 'reveal deferred'):
            m.sample_health_hud_context()

    def test_health_defers_when_target_is_a_familiar_clone(self):
        m, blocks, *_ = self.health_fixture()
        blocks[0x60000] = struct.pack('<Q', m.base + G.FAMILIAR_CLONE_PAWN_VTABLE)
        with self.assertRaisesRegex(PreloadError, 'reveal deferred'):
            m.sample_health_hud_context()

    def test_hotfix_base_observer_type_and_getters(self):
        m, blocks, _, services, _ = self.fixture()
        table = m.base + G.SERVICES_VTABLES[1]
        blocks[services] = struct.pack('<Q', table)
        blocks[table + G.OBSERVER_MODE_SLOT] = struct.pack('<Q', m.base + G.GET_OBSERVER_MODE)
        blocks[table + G.OBSERVER_TARGET_SLOT] = struct.pack('<Q', m.base + G.GET_OBSERVER_TARGET)
        self.assertEqual(m.sample_target()['handle'], 0x10002)
        # The prior build's nearby table must never satisfy this exact type gate.
        blocks[services] = struct.pack('<Q', m.base + 0x2a1c4e8)
        with self.assertRaisesRegex(PreloadError, 'object type differs'):
            m.sample_target()

    def test_prior_build_observer_getter_refused(self):
        m, blocks, *_ = self.fixture()
        blocks[m.base + G.SERVICES_VTABLES[0] + G.OBSERVER_MODE_SLOT] = struct.pack('<Q', m.base + 0x860a40)
        with self.assertRaisesRegex(PreloadError, 'getters differ'):
            m.sample_target()

    def test_recycled_handle_and_backpointer_refused(self):
        for backpointer in (False, True):
            m, blocks, chunk, _, target = self.fixture()
            address = target + G.IDENTITY_HANDLE if backpointer else chunk + 0xe0 + G.IDENTITY_HANDLE
            blocks[address] = struct.pack('<Q' if backpointer else '<I', 2)
            with self.assertRaises(PreloadError):
                m.sample_target()

    def test_wrong_type_or_mode_refused(self):
        for wrong_mode in (False, True):
            m, blocks, _, services, target = self.fixture()
            blocks[services + G.OBSERVER_MODE if wrong_mode else target] = (
                b'\x01' if wrong_mode else struct.pack('<Q', m.base + G.OBSERVER_PAWN_VTABLE))
            with self.assertRaises(PreloadError):
                m.sample_target()

    def test_torn_target_refused(self):
        m, blocks, _, services, _ = self.fixture()
        seen = set()
        def read(address, size):
            value = blocks[address][:size]
            if address == services + G.OBSERVER_TARGET and address in seen:
                return struct.pack('<I', 0x18002)
            seen.add(address)
            return value
        m.memory.read.side_effect = read
        with self.assertRaisesRegex(PreloadError, 'changed during'):
            m.sample_target()

    def test_unowned_does_not_read(self):
        m, *_ = self.fixture()
        m._owned.side_effect = PreloadError('unowned')
        with self.assertRaises(PreloadError):
            m.sample_target()
        m.memory.read.assert_not_called()


class FollowTargetBuildGateTests(unittest.TestCase):
    """Admit reviewed target code, and close before using an unreviewed build."""

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        profiles = root / 'native' / 'profiles'
        contract = json.loads((profiles / 'runtime-contracts.json').read_text(encoding='utf-8'))
        client = contract['modules']['client']
        profile = json.loads((profiles / client['profile']).read_text(encoding='utf-8'))
        self.current_digest = profile[client['section']][client['hash_key']]
        self.target_spans = tuple(
            (int(span['rva'], 16), span['size'])
            for span in contract['groups']['FollowTarget']['TARGET_SPANS']['value'])
        manifest = json.loads((profiles / 'manifest.json').read_text(encoding='utf-8'))
        self.stale_digest = next(
            digest for digest in manifest['modules'][client['path']]['accepted']
            if digest != self.current_digest)
        self.base = 0x180000000
        self.client_data = b'reviewed client image fixture'
        self.code = {(rva, size): bytes((rva + offset) % 256 for offset in range(size))
                     for rva, size in self.target_spans}
        self.memory = Mock()
        self.memory.read.side_effect = lambda address, size: self.code[address - self.base, size]

        def initialize(monitor, session):
            self.monitor = monitor
            monitor.command = [str(root / 'fixture-game' / 'game' / 'bin' / 'win64' / 'deadlock.exe')]
            monitor.base = self.base
            monitor.memory = self.memory
            self.addCleanup(monitor.close)

        superclass = patch('dolly.follow_target.FollowCapabilityMonitor.__init__',
                           autospec=True, side_effect=initialize)
        superclass.start()
        self.addCleanup(superclass.stop)
        game_file = patch('dolly.follow_target.game_file',
                          return_value=(self.client_data, self.current_digest))
        self.game_file = game_file.start()
        self.addCleanup(game_file.stop)
        image_bytes = patch('dolly.preload._image_bytes',
                            side_effect=lambda data, rva, size: self.code[rva, size])
        self.image_bytes = image_bytes.start()
        self.addCleanup(image_bytes.stop)

    def test_pin_matches_the_profile_the_anchors_were_reviewed_for(self):
        from dolly.follow_target import REVIEWED_CLIENT_SHA256
        self.assertEqual(self.current_digest, REVIEWED_CLIENT_SHA256)

    def test_current_reviewed_profile_admits_only_exact_target_spans(self):
        monitor = FollowTargetMonitor(Mock())
        self.assertIs(monitor.memory, self.memory)
        self.memory.close.assert_not_called()
        self.assertEqual(self.memory.read.call_args_list, [
            call(self.base + rva, size) for rva, size in self.target_spans])
        self.assertEqual(self.image_bytes.call_args_list, [
            call(self.client_data, rva, size) for rva, size in self.target_spans])

    def test_stale_or_unknown_client_refuses_before_target_reads_and_closes(self):
        for digest in (self.stale_digest, '0' * 64):
            with self.subTest(digest=digest):
                self.memory.reset_mock()
                self.game_file.return_value = self.client_data, digest
                with self.assertRaisesRegex(PreloadError, 'not reviewed for this game update'):
                    FollowTargetMonitor(Mock())
                self.memory.read.assert_not_called()
                self.image_bytes.assert_not_called()
                self.memory.close.assert_called_once_with()
                self.assertIsNone(self.monitor.memory)

    def test_patched_target_code_refuses_and_closes(self):
        for rva, size in self.target_spans:
            with self.subTest(rva=hex(rva)):
                self.memory.reset_mock()
                self.memory.read.side_effect = lambda address, count: (
                    b'\xff' * count if address == self.base + rva
                    else self.code[address - self.base, count])
                with self.assertRaisesRegex(PreloadError, 'observer code differs'):
                    FollowTargetMonitor(Mock())
                self.memory.close.assert_called_once_with()
                self.assertIsNone(self.monitor.memory)

    def test_future_camera_review_does_not_advance_target_pin(self):
        import importlib.util
        import dolly.follow_target as follow_target

        future_digest = '1' * 64
        self.assertNotEqual(future_digest, self.current_digest)
        source = Path(follow_target.__file__)
        spec = importlib.util.spec_from_file_location('dolly._follow_target_review_probe', source)
        probe = importlib.util.module_from_spec(spec)
        with patch('dolly.replay_camera.CLIENT_SHA256', future_digest), patch(
                'dolly._runtime_generated.ReplayCamera.CLIENT_SHA256', future_digest):
            spec.loader.exec_module(probe)
            self.assertEqual(probe.REVIEWED_CLIENT_SHA256, self.current_digest)
            with patch.object(probe, 'game_file', return_value=(self.client_data, future_digest)):
                with self.assertRaisesRegex(PreloadError, 'not reviewed for this game update'):
                    probe.FollowTargetMonitor(Mock())
        self.memory.read.assert_not_called()
        self.image_bytes.assert_not_called()
        self.memory.close.assert_called_once_with()
        self.assertIsNone(self.monitor.memory)
