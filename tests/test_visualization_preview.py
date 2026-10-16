"""Separate draft bytes cannot alter committed guides or camera commands."""
import copy
import ctypes
import math
import struct
import unittest
from unittest.mock import patch

from dolly import native_bridge as nb
from dolly import visualization_preview_wire as wire
from dolly.path import Keyframe, Project
from dolly.visualization_wire import build_visualization
from test_visualization_transport import Memory


class PreviewWireTransportTests(unittest.TestCase):
    def setUp(self):
        self.maps = []
        def factory(name, size):
            memory = Memory(size)
            self.maps.append((name, memory))
            return memory
        self.bridge = nb.NativeBridge.create(mapping_factory=factory, token='a'*32,
            editor_pid=1001, clock=lambda: 0, sleep=lambda _: None, start_heartbeat=False)
        self.addCleanup(self.bridge.close)
        self.project = Project(keyframes=[Keyframe(0, -10, 0, 0, 0, 0, 0),
                                          Keyframe(.25, 20, 5, 10, 0, 0, 0)])
        self.identity = dict(source=1, token=17, revision=7, session_id=0xF123456789ABCDEF,
                             selected_camera=1, channel=0, key_time=.25)
        self.packet = build_visualization(self.project, selected_camera=1,
            revision=7, session_id=self.identity['session_id'])

    def preview(self):
        memory = self.maps[-1][1]
        header = wire.HEADER.unpack_from(memory)
        return bytes(memory[:wire.HEADER_BYTES+header[11]])

    def test_envelope_layout_and_independent_mapping_keep_committed_and_control_bytes(self):
        self.bridge.publish_visualization(self.project, selected_camera=1, revision=7,
                                           session_id=self.identity['session_id'])
        original = [bytes(memory) for _, memory in self.maps]
        self.assertTrue(self.bridge.publish_visualization_preview(self.packet, **self.identity))
        self.assertEqual([bytes(memory) for _, memory in self.maps[:2]], original)
        self.assertEqual(self.maps[2][0], self.maps[0][0]+'.viewer.preview')
        self.assertEqual(len(self.maps[2][1]), 2*1024*1024)
        self.assertEqual(wire.HEADER.size, 64)
        self.assertEqual(wire.HEADER.unpack_from(self.preview()),
            (b'DLYPRV01', 2, 1, 1, 1, 17, 7, 0xF123456789ABCDEF, 1, 0, .25, len(self.packet), 0))
        self.assertEqual(self.preview()[64:], self.packet)
        self.assertEqual(self.project.keyframes[1].x, 20)

    def test_heartbeats_use_seqlock_and_reuse_identical_inner_bytes(self):
        self.assertTrue(self.bridge.publish_visualization_preview(self.packet, **self.identity))
        memory = self.maps[-1][1]
        odd_seen = []
        memory.observe = lambda _key, _value: odd_seen.append(struct.unpack_from('<I', memory, 8)[0])
        exchanged = []
        def exchange(pointer, value):
            slot = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int32))
            previous = slot.contents.value
            slot.contents.value = value.value
            exchanged.append(value.value)
            return previous
        self.bridge._atomic32 = exchange
        self.assertTrue(self.bridge.publish_visualization_preview(self.packet, **self.identity))
        self.assertEqual(exchanged, [3, 4])
        self.assertTrue(odd_seen and all(value == 3 for value in odd_seen))
        self.assertEqual(self.preview()[64:], self.packet)
        memory.observe = None
        self.bridge._preview_sequence = 0xFFFFFFFE
        self.assertTrue(self.bridge.publish_visualization_preview(self.packet, **self.identity))
        self.assertEqual(wire.HEADER.unpack_from(self.preview())[1], 2)

    def test_invalid_optional_packet_clears_only_draft_and_clears_do_not_allocate(self):
        self.assertTrue(self.bridge.publish_visualization_preview(None))
        self.assertEqual(len(self.maps), 1)
        self.bridge.publish_visualization(self.project)
        original = [bytes(memory) for _, memory in self.maps]
        self.bridge.publish_visualization_preview(self.packet, **self.identity)
        self.assertFalse(self.bridge.publish_visualization_preview(b'invalid', **self.identity))
        self.assertEqual(wire.HEADER.unpack_from(self.preview())[3:7], (0, 0, 0, 0))
        self.assertEqual([bytes(memory) for _, memory in self.maps[:2]], original)
        self.assertTrue(self.bridge.visualization_preview_diagnostics()['error'])
        self.assertTrue(self.bridge.publish_visualization_preview(self.packet, **self.identity))
        self.assertTrue(self.bridge.publish_visualization_preview(None, **self.identity))
        self.assertEqual(wire.HEADER.unpack_from(self.preview())[3:7], (0, 1, 17, 7))

    def test_identity_type_length_and_anchor_errors_are_refused(self):
        for changes in ({'source':0}, {'source':3}, {'token':0}, {'token':True},
                        {'token':1 << 32}, {'revision':0}, {'session_id':0},
                        {'channel':7}, {'channel':True}, {'selected_camera':0},
                        {'key_time':.125}, {'key_time':math.nan}, {'key_time':True},
                        {'sequence':3}, {'sequence':True}, {'sequence':1 << 32}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                wire.build_preview(self.packet, **dict(self.identity, **changes))
        for field, invalid in ((12,5), (16,0), (24,4097), (52,0), (56,4), (60,1)):
            packet = bytearray(self.packet)
            struct.pack_into('<I', packet, field, invalid)
            with self.subTest(field=field), self.assertRaises(ValueError):
                wire.build_preview(bytes(packet), **self.identity)
        with self.assertRaises(ValueError):
            wire.build_preview(self.packet+b'\0', **self.identity)

    def test_maximum_lens_packet_is_bounded_and_mapping_failure_is_optional(self):
        project = Project(keyframes=[Keyframe(i*.125, -10, 0, 0, 0, 0, 0, lens_scale=.875)
                                    for i in range(4096)])
        packet = build_visualization(project, revision=7, session_id=self.identity['session_id'])
        identity = dict(self.identity, selected_camera=0, key_time=0)
        wrapped = wire.build_preview(packet, **identity)
        self.assertEqual(len(wrapped), 1966048)
        self.assertLess(len(wrapped), wire.MAPPING_BYTES)
        invalid = Memory(128)
        with patch.object(self.bridge, '_mapping_factory', return_value=invalid):
            self.assertFalse(self.bridge.publish_visualization_preview(self.packet, **self.identity))
        self.assertEqual(invalid.closed, 1)
        self.assertEqual(len(self.maps), 1)

    def test_close_retires_draft_even_when_camera_release_fails(self):
        self.bridge.publish_visualization_preview(self.packet, **self.identity)
        memory = self.maps[-1][1]
        with patch.object(self.bridge, 'release', side_effect=nb.NativeBridgeError('camera unavailable')):
            self.bridge.close()
        self.assertEqual(memory.closed, 1)
        self.assertEqual(wire.HEADER.unpack_from(memory)[3:], (0,0,0,0,0,0,0,0,0,0))
        self.assertEqual(memory[64:], b'\0'*(wire.MAPPING_BYTES-64))


if __name__ == '__main__':
    unittest.main()
