"""
Offline tests for vram_daemon.py - the KV cache axis.

Moving the daemon between cache types is the one part of this tool that changes the machine,
so these tests patch the two things that touch it (the environment write and the restart
script) and assert on ORDER and on VERIFICATION rather than on effect. No PowerShell, no
Ollama, no GPU.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

import vram_daemon as vd  # noqa: E402


class TestAxisValueIsVerifiedNotAssumed(unittest.TestCase):
    def test_the_variable_is_written_before_the_restart(self):
        # The daemon reads OLLAMA_* once at start, so writing AFTER the restart is a no-op
        # and the sweep would then measure a rung believing a setting that is not active.
        order = []
        with mock.patch.object(vd, "_write_user_env",
                               side_effect=lambda *a: order.append("write")), \
             mock.patch.object(vd, "_run_restart_script",
                               side_effect=lambda *a: order.append("restart")), \
             mock.patch.object(vd, "active_kv_cache_type", return_value="q4_0"):
            vd.set_kv_cache_type("q4_0", Path("restart.ps1"))

        self.assertEqual(order, ["write", "restart"])

    def test_a_daemon_that_did_not_take_the_value_stops_the_run(self):
        # The 2026-08-14 orphan incident produced exactly this class of false measurement:
        # numbers attributed to a setting the daemon never had.
        with mock.patch.object(vd, "_write_user_env"), \
             mock.patch.object(vd, "_run_restart_script"), \
             mock.patch.object(vd, "active_kv_cache_type", return_value="q8_0"):
            with self.assertRaises(vd.DaemonError) as caught:
                vd.set_kv_cache_type("q4_0", Path("restart.ps1"))

        self.assertIn("q4_0", str(caught.exception))
        self.assertIn("q8_0", str(caught.exception))

    def test_a_missing_restart_script_is_named_not_ignored(self):
        with self.assertRaises(vd.DaemonError) as caught:
            vd._run_restart_script(Path("no-such-script.ps1"))

        self.assertIn("no-such-script.ps1", str(caught.exception))


class TestRestoreOnFailure(unittest.TestCase):
    def test_an_aborted_search_puts_the_daemon_back_on_its_original_value(self):
        # The machine must never be left on an axis value chosen by a search that failed:
        # the next unrelated run would measure against it without knowing.
        applied = []

        def fake_set(value, _script=None):
            applied.append(value)
            if value == "q4_0":
                raise vd.DaemonError("[VRAM-DAEMON] boom")

        with mock.patch.object(vd, "set_kv_cache_type", side_effect=fake_set):
            with self.assertRaises(vd.DaemonError):
                with vd.axis_restored("q8_0", Path("restart.ps1")) as apply_axis:
                    apply_axis("f16")
                    apply_axis("q4_0")

        self.assertEqual(applied[-1], "q8_0")

    def test_a_search_ending_on_the_original_value_does_not_restart_again(self):
        applied = []
        with mock.patch.object(vd, "set_kv_cache_type",
                               side_effect=lambda v, _s=None: applied.append(v)):
            with vd.axis_restored("q8_0", Path("restart.ps1")) as apply_axis:
                apply_axis("q8_0")

        self.assertEqual(applied, ["q8_0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
