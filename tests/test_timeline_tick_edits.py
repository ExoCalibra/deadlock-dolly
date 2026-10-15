import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from dolly.editor_dispatch import _dispatch
from dolly.path import Project, Keyframe


class TimelineTickEdits(unittest.TestCase):
    def app(self, rate=32, start=100, total=1000):
        project=Project(start_tick=start, tick_rate=rate,
                        keyframes=[Keyframe(0,1,2,3,0,0,0),Keyframe(1,4,5,6,0,0,0)])
        return SimpleNamespace(project=project, busy=False, playing=False,
            shot_history=SimpleNamespace(revision=7), _shot_edit_ready=lambda:True,
            _commit_camera=Mock(), status_text=Mock(),
            controller=SimpleNamespace(status=lambda:{'total_ticks':total}))

    def edit(self, app, time, revision=7):
        _dispatch(app, {'action':'set_camera_time','value':1,
                       'pose':[revision,time,1,0,0,0,0]}, object(), publish=lambda:None)
        return app._commit_camera.call_args.args[0][1].time

    def test_drag_uses_the_shot_clock_at_32_and_64_ticks(self):
        for rate in (32,64):
            app=self.app(rate=rate)
            before=copy.deepcopy(app.project)
            time=self.edit(app,.3333)
            self.assertEqual(100+time*rate,round(100+.3333*rate))
            self.assertEqual(app.project,before)

    def test_collision_moves_to_a_whole_free_tick(self):
        app=self.app()
        self.assertEqual(self.edit(app,0),1/32)

    def test_drag_clamps_at_the_last_replay_tick(self):
        app=self.app(total=140)
        self.assertEqual(self.edit(app,999),39/32)

    def test_rounding_ties_match_dolly_tick_labels(self):
        app=self.app()
        self.assertEqual(self.edit(app,10.5/32),10/32)

    def test_stale_revision_never_changes_a_camera(self):
        app=self.app()
        with self.assertRaises(ValueError): self.edit(app,.3,revision=6)
        app._commit_camera.assert_not_called()

    def test_unknown_clock_does_not_guess_a_tick_rate(self):
        app=self.app(); app.project.start_tick=None
        with self.assertRaisesRegex(ValueError,'clock'): self.edit(app,.3)
        app._commit_camera.assert_not_called()
