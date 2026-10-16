"""Public executable startup, safe handoff, recovery and package migration."""
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from dolly import release_launcher as boot, update_worker as worker, updater
from test_updater import package


class LauncherTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.target = Path(directory.name) / "Dolly folder"
        self.target.mkdir()
        (self.target / updater.MANIFEST).write_text("fixture")

    def test_normal_launch_cleans_up_and_opens_without_discovery_download_or_install(self):
        for arguments in ([], ["--updated"], ["--open", "shot.dolly"]):
            with self.subTest(arguments=arguments), \
                 patch.object(worker, "pending_work", return_value=None) as recovery, \
                 patch.object(worker, "cleanup_workspaces") as cleanup, \
                 patch.object(worker, "launch_program") as editor, \
                 patch.object(worker, "check_processes") as processes, \
                 patch.object(worker, "launch_worker") as install, \
                 patch.object(updater, "check_latest") as discovery, \
                 patch.object(updater, "download_update") as download, \
                 patch.object(updater, "open_url") as network:
                calls = Mock()
                calls.attach_mock(recovery, "recovery")
                calls.attach_mock(cleanup, "cleanup")
                calls.attach_mock(editor, "editor")
                self.assertEqual(boot.main(arguments, target=self.target), 0)
                self.assertEqual([call[0] for call in calls.mock_calls], ["recovery", "cleanup", "editor"])
                editor.assert_called_once_with(
                    [str(self.target.resolve() / "_internal/DollyApp.exe"), *arguments],
                    self.target.resolve(), wait=False)
                discovery.assert_not_called()
                download.assert_not_called()
                network.assert_not_called()
                processes.assert_not_called()
                install.assert_not_called()

    def test_ordinary_open_does_not_mark_the_editor_as_just_updated(self):
        with patch.object(worker, "launch_program") as launch:
            boot.open_editor(self.target)
            launch.assert_called_once_with(
                [str(self.target / "_internal/DollyApp.exe")], self.target, wait=False)

    def test_actual_update_argument_is_forwarded_unchanged(self):
        with patch.object(worker, "launch_program") as launch:
            boot.open_editor(self.target, ["--updated"])
            launch.assert_called_once_with(
                [str(self.target / "_internal/DollyApp.exe"), "--updated"], self.target, wait=False)

    def test_recovery_runs_without_the_editor_runtime_and_waits_for_bootloader(self):
        work = self.target / ".dolly-update-test"
        with patch.object(worker, "pending_work", return_value=work), \
             patch.object(boot, "launcher_process_ids", return_value=(123, 100)), \
             patch.object(worker, "check_processes") as check, patch.object(worker, "launch_worker") as launch, \
             patch.object(boot, "open_editor") as editor, \
             patch.object(worker, "cleanup_workspaces") as cleanup, \
             patch.object(updater, "check_latest") as discovery, \
             patch.object(updater, "download_update") as download:
            boot.main([], target=self.target)
            check.assert_called_once_with(self.target.resolve(), exclude_pid=(123, 100))
            launch.assert_called_once_with(self.target.resolve(), work, recover=True, parent_pid=100)
            editor.assert_not_called()
            cleanup.assert_not_called()
            discovery.assert_not_called()
            download.assert_not_called()

    def test_recovery_process_guard_still_blocks_an_unsafe_handoff(self):
        with patch.object(worker, "pending_work", return_value=self.target / ".dolly-update-test"), \
             patch.object(boot, "launcher_process_ids", return_value=(123, 100)), \
             patch.object(worker, "check_processes", side_effect=RuntimeError("Game is running")), \
             patch.object(worker, "launch_worker") as install, patch.object(boot, "open_editor") as editor:
            with self.assertRaisesRegex(RuntimeError, "Game is running"):
                boot.main([], target=self.target)
            install.assert_not_called()
            editor.assert_not_called()

    def test_install_health_check_bypasses_pending_recovery_and_network(self):
        for args in (["--self-test", "report.json"], ["--self-test-hidden", "report.json"],
                     ["--cleanup-session", "session.json"], ["--help"]):
            with self.subTest(args=args), patch.object(worker, "pending_work") as recovery, \
                 patch.object(worker, "cleanup_workspaces") as cleanup, \
                 patch.object(updater, "check_latest") as discovery, \
                 patch.object(worker, "launch_program", return_value=0) as launch:
                self.assertEqual(boot.main(args, target=self.target), 0)
                launch.assert_called_once_with(
                    [str(self.target.resolve() / "_internal/DollyApp.exe"), *args], self.target.resolve(), wait=True)
                recovery.assert_not_called()
                cleanup.assert_not_called()
                discovery.assert_not_called()

    def test_update_worker_entrypoints_still_bypass_editor_startup(self):
        for arguments, expected in ((["--plan", "plan.json"], ["--plan", "plan.json"]),
                                    (["--updater-self-test", "report.json"], ["--self-test", "report.json"])):
            with self.subTest(arguments=arguments), patch.object(worker, "main", return_value=7) as handoff, \
                 patch.object(worker, "pending_work") as recovery, patch.object(boot, "open_editor") as editor:
                self.assertEqual(boot.main(arguments, target=self.target), 7)
                handoff.assert_called_once_with(expected)
                recovery.assert_not_called()
                editor.assert_not_called()

    def test_new_process_has_independent_pyinstaller_runtime(self):
        with patch.object(worker.subprocess, "Popen") as launch:
            worker.launch_program(["Dolly.exe"], self.target)
            self.assertEqual(launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_legacy_manifest_migrates_to_single_public_executable(self):
        package(self.target, "1.0.0")
        work = self.target / ".dolly-update-migrate"
        package(work / "payload", "1.0.1")
        runtime = work / "payload/_internal/DollyApp.exe"
        runtime.write_text("new editor")
        (work / "payload/DollyUpdater.exe").unlink()
        updater.write_manifest(work / "payload", "1.0.1")
        self.assertEqual(updater.read_manifest(self.target)["schema"], 1)
        worker.install({"target": str(self.target), "work": str(work)})
        self.assertEqual(updater.read_manifest(self.target)["schema"], 2)
        self.assertFalse((self.target / "DollyUpdater.exe").exists())
        self.assertEqual((self.target / "_internal/DollyApp.exe").read_text(), "new editor")

    def test_pending_recovery_requires_matching_plan(self):
        work = self.target / ".dolly-update-test"; work.mkdir()
        plan = {"target": str(self.target), "work": str(work)}
        worker.atomic_json(self.target / worker.PENDING, plan)
        worker.atomic_json(work / "plan.json", {**plan, "target": str(self.target.parent)})
        with self.assertRaisesRegex(ValueError, "disagrees"):
            worker.pending_work(self.target)


class UpdateDiscoveryTests(unittest.TestCase):
    def release(self, tag="v0.6.50-alpha"):
        version = tag.removeprefix("v")
        name = f"Deadlock_Dolly_{version}_Windows_x64.zip"
        return {"tag_name": tag, "draft": False, "prerelease": False,
                "html_url": "https://untrusted.example/release-notes",
                "assets": [{"name": name, "state": "uploaded", "size": 100,
                            "digest": "sha256:" + "a" * 64,
                            "browser_download_url": f"https://github.com/{updater.REPOSITORY}/releases/download/{tag}/{name}"}]}

    def test_notes_url_is_bound_to_the_validated_official_release_tag(self):
        for tag in ("v0.6.50-alpha", "0.6.50-alpha", "v1.2.3-rc.4"):
            with self.subTest(tag=tag):
                selected = updater.select_release(self.release(tag), "0.6.49-alpha")
                self.assertEqual(selected["notes_url"],
                                 f"https://github.com/cravvnn/deadlock-dolly/releases/tag/{tag}")
                self.assertEqual(selected["sha256"], "a" * 64)

    def test_api_html_url_never_controls_the_notes_destination(self):
        for url in (None, "javascript:alert(1)", "file:///C:/notes.html",
                    "https://github.com/another/publisher/releases/tag/v0.6.50-alpha"):
            with self.subTest(url=url):
                release = self.release()
                release["html_url"] = url
                self.assertEqual(updater.select_release(release, "0.6.49-alpha")["notes_url"],
                                 "https://github.com/cravvnn/deadlock-dolly/releases/tag/v0.6.50-alpha")

    def test_unsupported_tags_cannot_become_notes_links(self):
        for tag in ("latest", "../v0.6.50-alpha", "v0.6.50-alpha?redirect=evil", "https://example.com"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                updater.select_release(self.release(tag), "0.6.49-alpha")

    def test_notes_link_does_not_bypass_release_asset_integrity_checks(self):
        for key, value in (("digest", None), ("size", True), ("size", updater.MAX_DOWNLOAD + 1),
                           ("browser_download_url", "https://untrusted.example/dolly.zip")):
            with self.subTest(key=key):
                release = self.release()
                release["assets"][0][key] = value
                with self.assertRaises(ValueError):
                    updater.select_release(release, "0.6.49-alpha")

    def test_discovery_fetches_only_metadata_and_never_stages_an_update(self):
        metadata = BytesIO(json.dumps(self.release()).encode())
        with patch.object(updater, "open_url", return_value=metadata) as network, \
             patch.object(updater, "download_update") as download, \
             patch.object(updater, "extract_verified") as extract:
            selected = updater.check_latest("0.6.49-alpha")
            self.assertEqual(selected["version"], "0.6.50-alpha")
            self.assertTrue(selected["notes_url"].endswith("/tag/v0.6.50-alpha"))
            network.assert_called_once_with(updater.LATEST_URL)
            download.assert_not_called()
            extract.assert_not_called()

    def test_discovery_keeps_the_metadata_size_limit(self):
        with patch.object(updater, "open_url", return_value=BytesIO(b" " * (2 * 1024 * 1024 + 1))), \
             patch.object(updater, "download_update") as download:
            with self.assertRaisesRegex(ValueError, "metadata is too large"):
                updater.check_latest("0.6.49-alpha")
            download.assert_not_called()
