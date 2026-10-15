import json
import unittest
from dataclasses import replace
from dolly.replay_events import decode_index
from dolly import replay_event_wire as wire


class ReplayEventsTests(unittest.TestCase):
    def data(self):
        return dict(abi=1,total_ticks=1000,kills=[dict(tick=100,killer=2,victim=1),
                    dict(tick=200,killer=1,victim=2)],
                    players=[dict(id=1,name='Ivy'),dict(id=2,name='Player 🐱')])

    def test_complete_index_keeps_all_events_and_names(self):
        index=decode_index(json.dumps(self.data()))
        self.assertEqual(index.kills,((100,2,1),(200,1,2)))
        self.assertEqual(index.players[1],(2,'Player 🐱'))
        packet=wire.pack(2,index)
        self.assertEqual(len(packet),wire.WIRE_BYTES)
        self.assertLessEqual(wire.OFFSET+len(packet),wire.MAPPING_BYTES)
        self.assertEqual(wire.KILL.unpack_from(packet,wire.HEADER.size),(100,2,1))

    def test_deaths_to_world_and_self_do_not_inflate_player_kill_total(self):
        data=self.data()
        data['players'].append(dict(id=0,name='World'))
        data['kills'] += [dict(tick=300,killer=0,victim=1), dict(tick=400,killer=2,victim=2)]
        index=decode_index(json.dumps(data))
        self.assertEqual(len(index.kills),4,'All deaths still need timeline markers')
        self.assertEqual(index.message,'2 player kills, 4 deaths in this replay')

    def test_rejects_partial_unsorted_or_out_of_range_events(self):
        for change in ('abi','length','range','order','duplicate','identity'):
            data=self.data()
            if change=='abi': data['abi']=9
            if change=='length': data['total_ticks']=0
            if change=='range': data['kills'][0]['tick']=1000
            if change=='order': data['kills'].reverse()
            if change=='duplicate': data['kills'].append(data['kills'][-1])
            if change=='identity': data['kills'][0]['killer']=15
            with self.subTest(change=change), self.assertRaises(ValueError):decode_index(json.dumps(data))

    def test_loading_and_unavailable_are_distinct_from_no_kills(self):
        data=self.data(); data['kills']=[]
        ready=decode_index(json.dumps(data))
        self.assertEqual(ready.status,2)
        for status in (0,1,3):
            self.assertEqual(wire.HEADER.unpack_from(wire.pack(4,replace(ready,status=status)))[3],status)

    def test_player_names_remain_valid_utf8_after_wire_truncation(self):
        index=decode_index(json.dumps(self.data()))
        packet=wire.pack(2,replace(index,players=((1,'🐱'*64),)))
        start=wire.HEADER.size+wire.MAX_KILLS*wire.KILL.size
        name=wire.PLAYER.unpack_from(packet,start)[1].split(b'\0')[0].decode('utf-8')
        self.assertTrue(name)

    def test_bridge_publishes_one_complete_packet_without_touching_existing_blocks(self):
        from dolly import native_bridge as nb
        memory=bytearray(nb.MAPPING_BYTES)
        bridge=nb.NativeBridge.create(mapping_factory=lambda *_:memory,start_heartbeat=False,
                                      editor_pid=100,token='b'*32)
        try:
            before=bytes(memory[:wire.OFFSET])
            bridge.configure_replay_events(decode_index(json.dumps(self.data())))
            self.assertEqual(bytes(memory[:wire.OFFSET]),before)
            header=wire.HEADER.unpack_from(memory,wire.OFFSET)
            self.assertEqual(header[:7],(b'DLYKILL1',2,1,2,2,2,1000))
        finally:bridge.close()

    def test_background_reader_reports_failure_and_never_keeps_old_markers(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from dolly.replay_events import ReplayEventReader
        with tempfile.TemporaryDirectory() as folder:
            replay=Path(folder)/'test.dem';replay.write_bytes(b'replay fixture')
            reader=ReplayEventReader()
            with patch('dolly.replay_events.threading.Thread'):
                self.assertEqual(reader.snapshot(replay).status,1)
            identity=reader._identity
            with patch('dolly.replay_events.subprocess.run',side_effect=OSError('Unsupported replay')):
                reader._read(replay,identity)
            self.assertEqual(reader.snapshot(replay).status,3)
            self.assertEqual(reader.snapshot(replay).kills,())
            self.assertEqual(reader.snapshot(None).status,0)
