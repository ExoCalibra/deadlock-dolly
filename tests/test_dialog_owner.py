"""Actual Windows/Tk modal ownership, visibility and focus regressions."""
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


NATIVE_OWNER_SCRIPT = textwrap.dedent(r'''
    import ctypes as C
    from ctypes import wintypes as W
    import json
    import sys
    import threading
    import time
    import tkinter as tk
    from tkinter import filedialog
    from dolly import dialogs

    mode = sys.argv[1]
    u = C.WinDLL('user32', use_last_error=True)
    k = C.WinDLL('kernel32')
    u.GetAncestor.argtypes = [W.HWND, W.UINT]; u.GetAncestor.restype = W.HWND
    u.GetWindow.argtypes = [W.HWND, W.UINT]; u.GetWindow.restype = W.HWND
    u.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    u.GetDlgItem.argtypes = [W.HWND, C.c_int]; u.GetDlgItem.restype = W.HWND
    u.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]; u.MonitorFromWindow.restype = W.HANDLE
    u.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    u.IsWindowEnabled.argtypes = [W.HWND]; u.IsWindowVisible.argtypes = [W.HWND]
    u.IsWindow.argtypes = [W.HWND]; u.IsIconic.argtypes = [W.HWND]
    u.EnableWindow.argtypes = [W.HWND, W.BOOL]
    u.GetActiveWindow.restype = W.HWND; u.GetFocus.restype = W.HWND
    u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    u.IsChild.argtypes = [W.HWND, W.HWND]
    class Info(C.Structure):
        _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT), ('flags', W.DWORD)]
    u.GetMonitorInfoW.argtypes = [W.HANDLE, C.POINTER(Info)]
    Callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    u.EnumThreadWindows.argtypes = [W.DWORD, Callback, W.LPARAM]

    def rect(window):
        result = W.RECT()
        assert u.GetWindowRect(window, C.byref(result))
        return [result.left, result.top, result.right, result.bottom]

    def contained(window, work):
        box = rect(window)
        bounds = (work.left, work.top, work.right, work.bottom)
        assert work.left <= box[0] < box[2] <= work.right, ('horizontal bounds', box, bounds)
        assert work.top <= box[1] < box[3] <= work.bottom, ('vertical bounds', box, bounds)
        return box

    root = tk.Tk(); root.geometry('500x300+100+100')
    entry = tk.Entry(root); entry.pack(); root.update(); entry.focus_force(); root.update()
    owner = u.GetAncestor(root.winfo_id(), 2)
    if mode == 'minimized': root.iconify(); root.update()
    if mode == 'offscreen': root.geometry('500x300+20000+20000'); root.update()
    if mode == 'disabled': u.EnableWindow(owner, False)
    main_thread = k.GetCurrentThreadId()
    focus_before = u.GetFocus()
    row = {'mode': mode}; errors = []
    dialogs._play_error_sound = lambda: None

    def observe_error():
        window = None
        try:
            deadline = time.monotonic() + 4
            while not dialogs._ACTIVE and time.monotonic() < deadline: time.sleep(.01)
            assert dialogs._ACTIVE, 'Native error missing'
            window = next(iter(dialogs._ACTIVE)); time.sleep(.1)
            info = Info(); info.cbSize = C.sizeof(info)
            assert u.GetMonitorInfoW(u.MonitorFromWindow(window, 2), C.byref(info))
            row['bounds'] = [contained(handle, info.rcWork) for handle in
                             (window, u.GetDlgItem(window, 1), u.GetDlgItem(window, 1001))]
            assert not u.IsWindowEnabled(owner)
            assert not u.IsIconic(owner)
            u.PostMessageW(window, 0x0010 if mode == 'close' else 0x0111, 0 if mode == 'close' else 1, 0)
        except BaseException as exc:
            errors.append(repr(exc))
            if window: u.PostMessageW(window, 0x0010, 0, 0)

    def ordinary():
        try:
            if mode == 'invalid':
                assert not u.IsWindow(1)
                try: dialogs._run_native_dialog(1, 'Invalid owner', 'failure', 'details')
                except OSError: pass
                else: raise AssertionError('Invalid owner was accepted')
            elif mode == 'failure':
                def fail(): raise RuntimeError('after owner disabled')
                dialogs._play_error_sound = fail
                try: dialogs._native_dialog(root, 'Failure restoration', 'failure', 'details')
                except RuntimeError as exc: assert str(exc) == 'after owner disabled'
                else: raise AssertionError('Injected presentation failure was lost')
            else:
                thread = threading.Thread(target=observe_error, daemon=True); thread.start()
                message = '\n'.join(['Long error detail'] * 200) if mode == 'long' else 'Example recording failure'
                assert dialogs._native_dialog(root, 'Owner regression', message, message)
                thread.join(1)
            assert bool(u.IsWindowEnabled(owner)) == (mode != 'disabled'), 'Owner enabled state changed'
            assert not dialogs._ACTIVE
            if mode in ('normal', 'close'):
                assert u.GetActiveWindow() == owner, 'Owner was not reactivated'
                assert u.GetFocus() == focus_before, 'Original focused control was not restored'
            row['restored'] = True
        except BaseException as exc: errors.append(repr(exc))
        finally:
            if mode == 'disabled': u.EnableWindow(owner, True)
            root.destroy()

    found = threading.Event(); error_returned = threading.Event()
    def observe_picker():
        picker = error = None
        try:
            deadline = time.monotonic() + 5
            while not picker and time.monotonic() < deadline:
                def visit(window, _):
                    nonlocal picker
                    title = C.create_unicode_buffer(256); u.GetWindowTextW(window, title, 256)
                    if title.value == 'Private modal owner regression' and u.IsWindowVisible(window): picker = window
                    return True
                callback = Callback(visit); u.EnumThreadWindows(main_thread, callback, 0); time.sleep(.01)
            assert picker, 'Visible native Save picker missing'
            assert not u.IsWindowEnabled(owner) and u.IsWindowEnabled(picker)
            found.set()
            while not dialogs._ACTIVE and time.monotonic() < deadline: time.sleep(.01)
            assert dialogs._ACTIVE, 'Nested error missing'
            error = next(iter(dialogs._ACTIVE)); time.sleep(.1)
            assert u.GetWindow(error, 4) == picker, 'Visible Save picker does not own its nested error'
            assert not u.IsWindowEnabled(owner) and not u.IsWindowEnabled(picker), 'Nested modal owner remained enabled'
            u.PostMessageW(error, 0x0111, 1, 0)
            assert error_returned.wait(2)
            assert not u.IsWindowEnabled(owner) and u.IsWindowEnabled(picker), 'Save modal owner state was not preserved'
            row['nested_owner_restored'] = True
            u.PostMessageW(picker, 0x0010, 0, 0)
        except BaseException as exc:
            errors.append(repr(exc))
            if error: u.PostMessageW(error, 0x0010, 0, 0)
            if picker: u.PostMessageW(picker, 0x0010, 0, 0)

    def nested_error():
        if not found.is_set(): root.after(20, nested_error); return
        try:
            assert dialogs._native_dialog(root, 'Nested error', 'Example failure', 'details')
            active, focus = u.GetActiveWindow(), u.GetFocus()
            assert active != owner and u.GetWindow(active, 4) == owner
            assert focus == active or u.IsChild(active, focus)
            row['picker_focus_restored'] = True
        except BaseException as exc: errors.append(repr(exc))
        finally: error_returned.set()

    def nested():
        thread = threading.Thread(target=observe_picker, daemon=True); thread.start()
        root.after(20, nested_error)
        try:
            assert filedialog.asksaveasfilename(parent=root, title='Private modal owner regression', defaultextension='.json') == ''
            thread.join(1)
            assert u.IsWindowEnabled(owner) and not dialogs._ACTIVE
        except BaseException as exc: errors.append(repr(exc))
        finally: root.destroy()

    root.after(20, nested if mode == 'nested' else ordinary); root.mainloop()
    print(json.dumps(dict(row, errors=errors)), flush=True)
    assert not errors, errors
''')


@unittest.skipUnless(sys.platform == "win32", "native Windows/Tk regression")
class NativeModalOwnerTests(unittest.TestCase):
    def check_owner(self, mode):
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", NATIVE_OWNER_SCRIPT, mode],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_error_and_buttons_fit_actual_work_area(self):
        for mode in ("normal", "minimized", "offscreen", "long"):
            with self.subTest(owner=mode):
                self.assertTrue(self.check_owner(mode)["restored"])

    def test_owner_state_survives_close_failure_and_invalid_owner(self):
        for mode in ("close", "disabled", "failure", "invalid"):
            with self.subTest(exit=mode):
                self.assertTrue(self.check_owner(mode)["restored"])

    def test_visible_save_picker_owns_nested_error_and_regains_focus(self):
        result = self.check_owner("nested")
        self.assertTrue(result["nested_owner_restored"])
        self.assertTrue(result["picker_focus_restored"])


if __name__ == "__main__":
    unittest.main()
