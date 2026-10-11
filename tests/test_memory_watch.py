"""Paused-memory watchdog logic, without a real game process or OS counters."""
import unittest

from dolly.memory_watch import PausedMemoryWatch


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class PausedMemoryWatchTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.values = {}
        self.watch = PausedMemoryWatch(sample=lambda pid: self.values.get(pid),
                                       clock=self.clock, threshold_bytes=1024,
                                       window_seconds=10.0, min_samples=3,
                                       sample_interval_seconds=1.0)

    def observe(self, *values, pid=100, tick=7):
        results = []
        for index, value in enumerate(values):
            self.values[pid] = value
            results.append(self.watch.observe(pid, paused=True, tick=tick))
            if index + 1 < len(values):
                self.clock.advance(1.0)
        return results

    def test_growth_under_the_threshold_never_warns(self):
        self.assertEqual(self.observe(1000, 1200, 1500, 1800), [None, None, None, None])

    def test_sustained_growth_warns_once_per_paused_episode(self):
        results = self.observe(1000, 1600, 2300, 2600)
        self.assertIsNone(results[0])
        self.assertIsNone(results[1])
        self.assertIn("Paused replay memory grew", results[2])
        self.assertIsNone(results[3])
        self.assertIsNone(self.watch.observe(100, paused=False))
        self.observe(50, 60, 70)
        resumed = self.observe(70, 4000)
        self.assertIn("Paused replay memory grew", resumed[1])

    def test_tick_change_resets_the_baseline(self):
        self.observe(1000, 1600)
        self.clock.advance(1.0)
        self.values[100] = 2600
        self.assertIsNone(self.watch.observe(100, paused=True, tick=8))
        self.assertEqual(self.observe(2700, 2800, 2900), [None, None, None])

    def test_unreadable_process_is_ignored_without_disarming(self):
        for _ in range(5):
            self.assertIsNone(self.watch.observe(100, paused=True, tick=7))
        results = self.observe(0, 600, 1300)
        self.assertIn("Paused replay memory grew", results[2])

    def test_stale_window_samples_are_discarded(self):
        self.values[100] = 0
        self.assertIsNone(self.watch.observe(100, paused=True, tick=7))
        self.clock.advance(20.0)
        self.values[100] = 5000
        self.assertIsNone(self.watch.observe(100, paused=True, tick=7))
        self.assertEqual(self.observe(5100, 5200), [None, None])

    def test_invalid_configuration_is_rejected(self):
        for kwargs in ({"threshold_bytes": 0}, {"window_seconds": -1},
                       {"min_samples": True}, {"min_samples": 0},
                       {"sample_interval_seconds": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PausedMemoryWatch(**kwargs)

    def test_samples_are_throttled_between_the_configured_interval(self):
        # The UI polls several times a second; a paused process must not open a
        # handle on every poll. Inside the interval the sample is skipped.
        opened = []
        watch = PausedMemoryWatch(sample=lambda pid: (opened.append(pid), 1000)[1],
                                  clock=self.clock, threshold_bytes=1024,
                                  window_seconds=10.0, min_samples=3,
                                  sample_interval_seconds=3.0)
        self.assertIsNone(watch.observe(100, paused=True, tick=7))
        for _ in range(20):  # 20 rapid polls inside the same interval.
            self.assertIsNone(watch.observe(100, paused=True, tick=7))
        self.assertEqual(opened, [100])  # One sample for the whole interval.
        self.clock.advance(3.0)
        watch.observe(100, paused=True, tick=7)
        self.assertEqual(opened, [100, 100])


if __name__ == "__main__":
    unittest.main()
