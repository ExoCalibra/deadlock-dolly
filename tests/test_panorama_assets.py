"""Panorama resources fail closed before a new owned native deployment."""
import binascii
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from dolly import panorama_assets as assets


def write_vpk(index, entries, *, version=2, preload=0, external=False):
    """Create small independent inline/archive fixtures, including preload bytes."""
    pairs = list(entries.items()) if isinstance(entries, dict) else list(entries)
    groups = {}
    for name, payload in pairs:
        path = Path(name)
        groups.setdefault((path.suffix[1:], path.parent.as_posix()), []).append((path.stem, payload))
    tree = bytearray()
    data = bytearray()
    for extension in sorted({key[0] for key in groups}):
        tree += extension.encode() + b'\0'
        for (ext, directory), members in sorted(groups.items()):
            if ext != extension:
                continue
            tree += directory.encode() + b'\0'
            for name, payload in members:
                head = payload[:preload]
                tail = payload[preload:]
                tree += name.encode() + b'\0'
                tree += struct.pack('<IHHIIH', binascii.crc32(payload) & 0xffffffff,
                                    len(head), 0 if external else 0x7fff, len(data), len(tail), 0xffff)
                tree += head
                data += tail
            tree += b'\0'
        tree += b'\0'
    tree += b'\0'
    header = struct.pack('<III', 0x55aa1234, version, len(tree))
    if version == 2:
        header += struct.pack('<IIII', 0 if external else len(data), 0, 0, 0)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_bytes(header + tree + (b'' if external else data))
    if external:
        index.with_name(index.name[:-8] + '_000.vpk').write_bytes(data)


class PanoramaAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = self.root / 'pak01_dir.vpk'
        self.stock = {name: ('stock fixture ' + name).encode() for name in assets.STOCK_UI_SHA256}
        self.pins = {name: hashlib.sha256(payload).hexdigest() for name, payload in self.stock.items()}

    def test_named_stock_resources_read_inline_external_and_preload(self):
        for version in (1, 2):
            for external in (False, True):
                with self.subTest(version=version, external=external):
                    write_vpk(self.index, self.stock, version=version, external=external, preload=5)
                    self.assertEqual(assets.read_vpk_entries(self.index, self.stock), self.stock)
                    with patch.object(assets, 'STOCK_UI_SHA256', self.pins):
                        assets.verify_stock_ui_assets(self.root)

    def test_changed_missing_and_crc_damaged_stock_are_rejected(self):
        cases = [dict(self.stock), dict(list(self.stock.items())[1:])]
        cases[0][next(iter(self.stock))] += b' game update'
        for payloads in cases:
            write_vpk(self.index, payloads)
            with self.subTest(names=list(payloads)), patch.object(assets, 'STOCK_UI_SHA256', self.pins):
                with self.assertRaisesRegex(ValueError, 'shader loading UI could not be verified'):
                    assets.verify_stock_ui_assets(self.root)
        write_vpk(self.index, self.stock)
        data = bytearray(self.index.read_bytes()); data[-1] ^= 1; self.index.write_bytes(data)
        with patch.object(assets, 'STOCK_UI_SHA256', self.pins), self.assertRaisesRegex(ValueError, 'CRC'):
            assets.verify_stock_ui_assets(self.root)

    def test_truncation_limits_duplicate_and_missing_archives_fail_closed(self):
        for blob in (b'', b'not a VPK index', struct.pack('<III', 0x55aa1234, 2, 0x7fffffff)):
            self.index.write_bytes(blob)
            with self.subTest(blob=blob), self.assertRaises(ValueError):
                assets.read_vpk_entries(self.index, self.stock)
        write_vpk(self.index, self.stock)
        with self.assertRaisesRegex(ValueError, 'oversized'):
            assets.read_vpk_entries(self.index, self.stock, max_payload_bytes=1)
        name, payload = next(iter(self.stock.items()))
        write_vpk(self.index, [(name, payload), (name, payload)])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            assets.read_vpk_entry(self.index, name)
        write_vpk(self.index, self.stock, external=True)
        self.index.with_name('pak01_000.vpk').unlink()
        with patch.object(assets, 'STOCK_UI_SHA256', self.pins), self.assertRaisesRegex(ValueError, 'shader loading UI'):
            assets.verify_stock_ui_assets(self.root)

    def test_shipped_pack_is_exact_accepted_five_resource_card_and_capture_clean_payloads(self):
        from dolly.launcher import UI_OVERRIDE_PACK, UI_OVERRIDE_PACK_SHA256
        self.assertEqual(UI_OVERRIDE_PACK_SHA256, '0af30912a471efc984e653ebc57a4c05f210e07f707f42d3bec997fc945b2fe1')
        self.assertEqual(hashlib.sha256(UI_OVERRIDE_PACK.read_bytes()).hexdigest(), UI_OVERRIDE_PACK_SHA256)
        payloads = assets.read_vpk_entries(UI_OVERRIDE_PACK, assets.OVERRIDE_RESOURCES)
        self.assertEqual(len(payloads), 5)
        for name, expected in {
            'panorama/styles/citadel_client_status.vcss_c': 'e13218f995880a59727d3cd3dd043f236fd67959c7962d3ade3429c56a6017c4',
            'panorama/styles/citadel_hud_and_db_overlay.vcss_c': '13c7907c48109f40dd5a7bb23895b60f6d7b0308d0508659451cd96cdae28d41',
        }.items():
            self.assertEqual(hashlib.sha256(payloads[name]).hexdigest(), expected)
        source = Path(__file__).resolve().parents[1] / 'native/ui_override'
        layout = ET.parse(source / 'panorama/layout/hud_hideout.xml').getroot()
        main = layout.find("CitadelHudHideout/Panel[@class='MainContents']")
        host = main.find("Panel[@id='DollyShaderNoticeAnchorV2']")
        self.assertEqual(host.attrib['hittestchildren'], 'false')
        self.assertIn('16%', host.find("CitadelPrewarmAssetsStatus[@id='PrewarmStatus']").attrib['style'])
        self.assertIsNone(main.find("Panel[@class='BottomRight']/CitadelPrewarmAssetsStatus"))

    def test_build_tool_requires_and_compiles_both_layouts_and_all_three_styles(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('build_ui_override_test', root / 'tools/build_ui_override.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        self.assertEqual(tool.EXPECTED_RESOURCES, assets.OVERRIDE_RESOURCES)
        sdk = self.root / 'sdk'
        (sdk / 'game/citadel').mkdir(parents=True)
        (sdk / 'game/citadel/gameinfo.gi').write_text('fixture')
        calls = []
        def compile_one(command, **kwargs):
            target = Path(command[command.index('-i') + 1])
            relative = target.relative_to(sdk / 'content/citadel_addons' / tool.ADDON)
            produced = (sdk / 'game/citadel_addons' / tool.ADDON / relative).with_suffix(tool.EXPECTED_SOURCES[relative.as_posix()])
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b'ClientServerDebugStats GameLogoIcon DollyLoadingProbeV2 ' + relative.as_posix().encode())
            calls.append(target.suffix)
            return SimpleNamespace(returncode=0)
        with patch.object(tool.subprocess, 'run', side_effect=compile_one):
            output, compiled = tool.compile_sources(sdk, self.root / 'resourcecompiler.exe')
        self.assertEqual(sorted(calls), ['.css', '.css', '.css', '.xml', '.xml'])
        destination = self.root / 'pak02_dir.vpk'
        tool.pack(output, compiled, destination)
        self.assertEqual(set(assets.read_vpk_entries(destination, assets.OVERRIDE_RESOURCES)), assets.OVERRIDE_RESOURCES)
        with self.assertRaisesRegex(SystemExit, 'exactly the five'):
            tool.pack(output, [p for p in compiled if p.suffix != '.vxml_c'], destination)
        source = self.root / 'incomplete_sources'; source.mkdir()
        with patch.object(tool, 'SOURCE', source), self.assertRaisesRegex(SystemExit, 'two layouts'):
            tool.compile_sources(sdk, self.root / 'resourcecompiler.exe')

    def test_source_export_includes_all_reviewed_ui_sources(self):
        root = Path(__file__).resolve().parents[1]
        listed = set((root / 'SOURCE_FILES.txt').read_text(encoding='utf-8').splitlines())
        sources = {path.relative_to(root).as_posix() for path in (root / 'native/ui_override').rglob('*')
                   if path.is_file() and path.suffix in ('.css', '.xml')}
        self.assertEqual(len(sources), 5)
        self.assertLessEqual(sources, listed)

    def test_controller_clears_original_native_publisher_bit_and_cached_refresh(self):
        from dolly.controller import Controller
        from dolly.lite_mode import REPLAY_INFO, REPLAY_INFO_OFFSET
        from dolly.native_bridge import NativeBridge, MAPPING_BYTES
        from dolly.path import Project
        class Memory(bytearray):
            def close(self):
                pass
        memory = Memory(MAPPING_BYTES)
        bridge = NativeBridge.create(mapping_factory=lambda name, size: memory,
                                     start_heartbeat=False, editor_pid=1001, token='a'*32)
        self.addCleanup(bridge.close)
        controller = Controller(); controller._session = SimpleNamespace(native=bridge)
        bridge.configure_shader_loading(True)
        previous = REPLAY_INFO.unpack_from(memory, REPLAY_INFO_OFFSET)[1]
        for stage in ('waiting_preload_intro', 'preloading', 'preload_ready', 'editing_ready'):
            controller._message(stage, startup_stage=stage)
            packet = REPLAY_INFO.unpack_from(memory, REPLAY_INFO_OFFSET)
            self.assertEqual(packet[6] & 4, 0)
            self.assertEqual(packet[1] & 1, 0)
            self.assertGreater(packet[1], previous)
            self.assertEqual(controller._state['startup_stage'], stage)
            previous = packet[1]
            bridge.configure_lite_replay(Project(), 1, total_ticks=120)
            self.assertEqual(REPLAY_INFO.unpack_from(memory, REPLAY_INFO_OFFSET)[6] & 4, 0)
            previous = REPLAY_INFO.unpack_from(memory, REPLAY_INFO_OFFSET)[1]
