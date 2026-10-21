"""Movie WAV capture parsing and conversion."""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import Mock, patch

from dolly.movie_audio import MOVIE_START, MovieOutputContext, MovieWave


class MovieWaveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.game = Path(self.folder.name) / "Deadlock/game/bin/win64/deadlock.exe"
        self.game.parent.mkdir(parents=True)
        self.movie = MovieWave(Path(self.folder.name) / "shot.mp4", self.game)
        self.controller = Mock()
        self.controller.game_pid.return_value = 4321
        self.marker = Path(tempfile.gettempdir()) / "dolly_movie_audio_4321.ready"

    def tearDown(self):
        self.marker.unlink(missing_ok=True)

    def test_start_parses_the_engine_folder(self):
        self.marker.write_text("", encoding="ascii")
        self.controller.replay_tick_rate.return_value = 64.0
        self.controller._request.side_effect = [
            "",
            "Audio device starved 3 samples \r\n"
            "Started recording movie: movie/2026_10_19_12_00_00/dolly_audio_x.*: "
            "framerate 60.000000",
            "Syntax: demo_goto <tick>\r\n  Currently playing 45 of 1000 ticks.",
        ]
        self.movie.start(self.controller, 60)
        self.assertTrue(self.movie.started)
        self.assertAlmostEqual(self.movie.movie_engine_seconds, 45 / 64.0)
        self.assertEqual(
            self.movie.folder,
            Path(self.folder.name) / "Deadlock/game/citadel/movie/2026_10_19_12_00_00")

    def test_start_refuses_without_the_native_marker(self):
        self.marker.unlink(missing_ok=True)
        with self.assertRaisesRegex(RuntimeError, "does not support fixed-step audio"):
            self.movie.start(self.controller, 60)

    def test_finish_converts_the_wav_to_48k(self):
        self.marker.write_text("", encoding="ascii")
        self.controller.replay_tick_rate.return_value = 64.0
        self.controller._request.side_effect = [
            "",
            "Started recording movie: movie/2026_10_19_12_00_00/dolly_audio_x.*: "
            "framerate 60.000000",
            "Syntax: demo_goto <tick>\r\n  Currently playing 0 of 1000 ticks.",
        ]
        self.movie.start(self.controller, 60)
        assert self.movie.folder is not None
        self.movie.folder.mkdir(parents=True, exist_ok=True)
        source = self.movie.folder / f"{self.movie.name}.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44100)
            audio.writeframes(b"\0\0\0\0" * 44100)
        self.controller._request.side_effect = [
            "Finishing movie: movie/2026_10_19_12_00_00/dolly_audio_x.* "
            "[60 frames @ 60.000000 == 1.000000 seconds]"
        ]
        try:
            target = self.movie.finish(self.controller, 0.25, Path(self.folder.name),
                                       start_engine_seconds=0.25, speed=0.5)
        except RuntimeError as exc:
            self.skipTest(f"FFmpeg unavailable: {exc}")
        self.assertTrue(target.is_file())
        with wave.open(str(target), "rb") as audio:
            self.assertEqual(audio.getframerate(), 48000)
            self.assertEqual(audio.getnchannels(), 2)
            self.assertGreaterEqual(audio.getnframes(), 11000)
            self.assertLessEqual(audio.getnframes(), 13000)


class OwnedMovieWaveTests(unittest.TestCase):
    def test_clip_audio_collects_the_owned_mod_wav_and_keeps_the_legacy_sentinel(self):
        from dolly.clip_audio import ClipAudioCapture
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            game=folder/'Deadlock/game/bin/win64/deadlock.exe'
            own=folder/'Deadlock/game/citadel_dolly_test/cvar_unlocker/movie'
            controller=Mock()
            controller.game_pid.return_value=None
            controller._native_bridge.return_value.status.return_value={'engine_time':0}
            controller.movie_output_context.return_value=MovieOutputContext(own,Mock())
            controller._request.side_effect=lambda command,**kw: (
                'Started recording movie: movie/2026_10_20_18_01_38/dolly_audio_x.*: framerate 30'
                if command.startswith('startmovie ') else 'Finishing movie' if command=='endmovie' else '')
            with patch('dolly.clip_audio._ffmpeg',return_value=folder/'ffmpeg.exe'):
                audio=ClipAudioCapture(folder/'shot.mkv',game_audio=True,reconstructed=False,
                    bridge=Mock(),game=game,game_pid=123,controller=controller,fixed_step=True)
            audio.start_movie()
            name=audio.movie.name+'.wav'
            actual=own/'2026_10_20_18_01_38'/name
            wrong=folder/'Deadlock/game/citadel/movie/2026_10_20_18_01_38'/name
            actual.parent.mkdir(parents=True);actual.write_bytes(b'owned engine WAV')
            wrong.parent.mkdir(parents=True);wrong.write_bytes(b'unrelated legacy sentinel')
            def convert(command,**kwargs):
                self.assertEqual(Path(command[command.index('-i')+1]),actual)
                Path(command[-1]).write_bytes(b'converted audio')
                return SimpleNamespace(returncode=0,stderr='')
            with patch('dolly.clip_audio._ffmpeg',return_value=folder/'ffmpeg.exe'), \
                    patch('dolly.movie_audio.subprocess.run',side_effect=convert):
                result=audio.movie.finish(controller,.25,folder)
            self.assertTrue(result.is_file())
            self.assertEqual(wrong.read_bytes(),b'unrelated legacy sentinel')
            self.assertFalse(actual.exists())
            audio.temporary.cleanup()


class MovieLifetimeTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name);self.root=self.base/'owned/movie'
        self.date=self.root/'2026_10_20_18_01_38';self.date.mkdir(parents=True)
        self.controller=Mock();self.controller.game_pid.return_value=None
        self.controller._native_bridge.return_value.status.return_value={'engine_time':0}
        self.controller._request.side_effect=lambda command,**kw: (
            'Started recording movie: movie/2026_10_20_18_01_38/dolly_audio_x.*: framerate 30'
            if command.startswith('startmovie ') else 'Finishing movie' if command=='endmovie' else '')
        self.allowed=True
        def verify(controller):
            if not self.allowed or controller is not self.controller:raise RuntimeError('Original movie owner unavailable')
        self.movie=MovieWave(self.base/'video.mkv',self.base/'game/bin/win64/deadlock.exe',
            output_context=MovieOutputContext(self.root,verify))
        self.movie.start(self.controller,30)
        self.wav=self.date/(self.movie.name+'.wav');self.wav.write_bytes(b'owned WAV')
        self.controller._request.reset_mock()

    def test_cancel_deletes_only_exact_own_wav_and_preserves_unknown_siblings(self):
        sibling=self.date/'unrelated.wav';sibling.write_bytes(b'keep')
        self.movie.cancel(self.controller)
        self.assertFalse(self.wav.exists());self.assertTrue(sibling.is_file())
        self.assertEqual(sibling.read_bytes(),b'keep')
        self.assertTrue(self.root.exists())

    def test_clean_owned_take_removes_only_empty_date_and_movie_roots(self):
        self.movie.cancel(self.controller)
        self.assertFalse(self.date.exists());self.assertFalse(self.root.exists())
        self.assertTrue(self.root.parent.is_dir())

    def test_owner_loss_refuses_finish_cancel_and_cleanup_without_commands_or_deletion(self):
        self.allowed=False
        for action in (lambda:self.movie.finish(self.controller,.25,self.base),
                       lambda:self.movie.cancel(self.controller),self.movie.cleanup):
            with self.assertRaisesRegex(RuntimeError,'owner unavailable'):action()
        self.controller._request.assert_not_called();self.assertEqual(self.wav.read_bytes(),b'owned WAV')

    def test_wrong_controller_cannot_finish_or_cancel_the_original_movie(self):
        wrong=Mock()
        for action in (lambda:self.movie.finish(wrong,.25,self.base),lambda:self.movie.cancel(wrong)):
            with self.assertRaisesRegex(RuntimeError,'controller changed'):action()
        wrong._request.assert_not_called();self.controller._request.assert_not_called()
        self.assertEqual(self.wav.read_bytes(),b'owned WAV')

    def test_reassigned_root_or_capture_name_refuses_without_fallback(self):
        self.movie.movie_root=self.base/'legacy/movie'
        with self.assertRaisesRegex(RuntimeError,'root changed'):self.movie.cancel(self.controller)
        self.movie.movie_root=self.root;self.movie.name='other'
        with self.assertRaisesRegex(RuntimeError,'capture identity'):self.movie.cleanup()
        self.controller._request.assert_not_called();self.assertTrue(self.wav.is_file())

    def test_owner_change_after_hideconsole_prevents_startmovie_dispatch(self):
        fresh=MovieWave(self.base/'new.mkv',self.base/'game/bin/win64/deadlock.exe',
                        output_context=self.movie._output_context)
        def hide(command,**kwargs):
            self.allowed=False
            return ''
        self.controller._request.side_effect=hide
        with self.assertRaisesRegex(RuntimeError,'owner unavailable'):fresh.start(self.controller,30)
        self.assertEqual([call.args[0] for call in self.controller._request.call_args_list],['hideconsole'])
        self.assertEqual(self.wav.read_bytes(),b'owned WAV')

    def test_owner_change_during_endmovie_preserves_wav_before_conversion(self):
        def end(command,**kwargs):
            self.allowed=False
            return 'Finishing movie'
        self.controller._request.side_effect=end
        with patch('dolly.movie_audio.subprocess.run') as convert:
            with self.assertRaisesRegex(RuntimeError,'owner unavailable'):
                self.movie.finish(self.controller,.25,self.base)
        convert.assert_not_called();self.assertEqual(self.wav.read_bytes(),b'owned WAV')

    def test_replaced_or_linked_date_directory_is_preserved(self):
        retained=self.root/'retained';self.assertTrue(retained.resolve().is_relative_to(self.base.resolve()))
        self.date.rename(retained);self.date.mkdir()
        with self.assertRaisesRegex(RuntimeError,'directory changed'):self.movie.cleanup()
        self.date.rmdir()
        if __import__('sys').platform=='win32':
            import _winapi
            _winapi.CreateJunction(str(retained),str(self.date))
        else:self.date.symlink_to(retained,target_is_directory=True)
        try:
            with self.assertRaisesRegex(RuntimeError,'Linked movie'):self.movie.cancel(self.controller)
            self.assertEqual((retained/self.wav.name).read_bytes(),b'owned WAV')
            self.controller._request.assert_not_called()
        finally:
            if __import__('sys').platform=='win32':self.date.rmdir()
            else:self.date.unlink()

    def test_direct_legacy_constructor_keeps_stock_movie_root_and_unknown_files(self):
        legacy=MovieWave(self.base/'legacy.mkv',self.base/'game/bin/win64/deadlock.exe')
        legacy.start(self.controller,30)
        legacy.folder.mkdir(parents=True)
        own=legacy.folder/(legacy.name+'.wav');own.write_bytes(b'legacy own')
        sibling=legacy.folder/'other.wav';sibling.write_bytes(b'keep legacy')
        legacy.cancel(self.controller)
        self.assertFalse(own.exists());self.assertTrue(sibling.is_file())
        self.assertEqual(sibling.read_bytes(),b'keep legacy')
        self.assertTrue(legacy.movie_root.is_dir())


if __name__ == "__main__":
    unittest.main()
