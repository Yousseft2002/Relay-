"""End-to-end loop against a real local git repo and an in-memory GitHub."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from relay.ledger import Ledger
from relay.workflows import Relay

from .helpers import FakeGitHub, FakeRunner, make_config, make_repo


def remote_branches(repo):
    out = subprocess.run(["git", "ls-remote", "--heads", "origin"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    return [line.split("refs/heads/")[1] for line in out.splitlines()]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = make_repo(Path(self._tmp.name))
        self.cfg = make_config(self.repo)
        self.gh = FakeGitHub()

    def tearDown(self):
        self._tmp.cleanup()

    def prs(self):
        return [n for n, i in self.gh.items.items() if i.get("is_pr")]

    def test_plan_creates_spec_and_ordered_tasks(self):
        gh = self.gh
        relay = Relay(self.cfg, gh, runner=FakeRunner())
        self.assertIn("Spec #1 with 2 tasks", relay.plan("add login"))
        self.assertEqual(gh.items[1]["labels"], ["relay:spec"])
        self.assertTrue({"relay:ready", "size:S"} <= set(gh.labels(2)))
        self.assertIn("Depends on: #2", gh.items[3]["body"])
        # task 3 isn't ready until #2 is closed
        self.assertEqual(relay.next_ready_issue()["number"], 2)
        gh.items[2]["labels"].append("relay:in-progress")
        self.assertIsNone(relay.next_ready_issue())
        gh.items[2]["state"] = "CLOSED"
        self.assertEqual(relay.next_ready_issue()["number"], 3)

    def test_full_loop_build_review_merge(self):
        gh = self.gh
        relay = Relay(self.cfg, gh, runner=FakeRunner(verdicts=["approve"]))
        issue = gh.create_issue("Add CI", "## Goal\nCI", ["relay:ready", "size:S"])

        self.assertIn("built by codex", relay.dispatch())
        pr = self.prs()[0]
        self.assertTrue({"relay:review", "built-by:codex", "size:S"} <= set(gh.labels(pr)))
        self.assertIn(f"Closes #{issue}", gh.items[pr]["body"])
        self.assertIn(f"relay/issue-{issue}", remote_branches(self.repo))

        self.assertIn("approved by claude", relay.review())  # codex built it -> claude reviews
        self.assertTrue({"relay:approved", "risk:low"} <= set(gh.labels(pr)))

        notes = relay.merge_ready()  # no CI reported -> waits for a human
        self.assertIn("no CI checks", notes[0])
        self.assertIn("relay:needs-human", gh.labels(pr))
        self.assertEqual(relay.merge_ready(), [])  # doesn't nag twice
        gh.items[pr]["labels"].remove("relay:needs-human")
        gh.items[pr]["statusCheckRollup"] = [{"name": "test", "conclusion": "SUCCESS"}]
        notes = relay.merge_ready()
        self.assertEqual(gh.merged, [pr])
        self.assertIn("Merged", notes[0])

        usage = Ledger(self.cfg.state_dir).usage_today()
        self.assertEqual((usage["codex"]["runs"], usage["codex"]["tokens"]), (1, 1000))
        self.assertAlmostEqual(usage["claude"]["usd"], 0.5)

    def test_failed_ci_sends_pr_back(self):
        gh = self.gh
        relay = Relay(self.cfg, gh, runner=FakeRunner(verdicts=["approve"]))
        gh.create_issue("Add CI", "ci", ["relay:ready", "size:S"])
        relay.dispatch()
        relay.review()
        pr = self.prs()[0]
        gh.items[pr]["statusCheckRollup"] = [{"name": "lint", "conclusion": "FAILURE"}]
        self.assertIn("CI failed", relay.merge_ready()[0])
        self.assertIn("relay:changes-requested", gh.labels(pr))
        self.assertIn("built by codex", relay.rework())

    def test_changes_requested_then_rework_then_human(self):
        gh = self.gh
        runner = FakeRunner(verdicts=["request_changes"] * 3)
        relay = Relay(self.cfg, gh, runner=runner)
        gh.create_issue("Login page", "page", ["relay:ready", "size:M"])
        relay.dispatch()
        pr = self.prs()[0]

        self.assertIn("requested changes", relay.review())
        self.assertTrue({"relay:changes-requested", "rework:1"} <= set(gh.labels(pr)))

        self.assertIn("built by codex", relay.rework())
        self.assertIn("relay:review", gh.labels(pr))
        self.assertNotIn("relay:changes-requested", gh.labels(pr))
        self.assertEqual(len(self.prs()), 1)  # rework updates the same PR

        relay.review()
        self.assertIn("rework:2", gh.labels(pr))
        self.assertNotIn("rework:1", gh.labels(pr))
        relay.rework()
        msg = relay.review()  # third failed review -> human
        self.assertIn("needs you", msg)
        self.assertIn("relay:needs-human", gh.labels(pr))

    def test_blocked_build_flags_human(self):
        gh = self.gh
        relay = Relay(self.cfg, gh, runner=FakeRunner(build_status="blocked"))
        n = gh.create_issue("Pick a database", "?", ["relay:ready", "size:M"])
        self.assertIn("blocked", relay.dispatch())
        self.assertTrue({"relay:blocked", "relay:needs-human"} <= set(gh.labels(n)))
        self.assertEqual(self.prs(), [])

    def test_cloud_dispatch_and_pickup(self):
        gh = self.gh
        cfg = make_config(self.repo, text=(self.repo / "relay.toml").read_text().replace(
            'S = "codex"', 'S = "copilot-cloud"'))
        relay = Relay(cfg, gh, runner=FakeRunner())
        n = gh.create_issue("Fix typo", "typo", ["relay:ready", "size:S"])
        self.assertIn("cloud agent", relay.dispatch())
        self.assertEqual(gh.copilot_assigned, [n])

        # Copilot opens a draft PR, then marks it ready
        pr = gh._new(title="Fix typo", body=f"Fixes #{n}", labels=[], headRefName="copilot/fix",
                     is_pr=True, isDraft=True, statusCheckRollup=[])
        self.assertEqual(relay.sync_cloud_prs(), [])
        gh.items[pr]["isDraft"] = False
        self.assertIn("queued for review", relay.sync_cloud_prs()[0])
        self.assertTrue({"relay:review", "built-by:copilot-cloud", "size:S"} <= set(gh.labels(pr)))

    def test_tick_respects_pause_and_runs_loop(self):
        gh = self.gh
        relay = Relay(self.cfg, gh, runner=FakeRunner())
        gh.create_issue("A", "a", ["relay:ready", "size:S"])
        relay.set_stop(True)
        self.assertIn("paused", relay.tick())
        relay.set_stop(False)
        report = relay.tick()
        self.assertIn("built by codex", report)
        self.assertIn("approved by claude", relay.tick())
        status = relay.status()
        self.assertIn("Today's usage", status)
        self.assertIn("approved by claude", status)  # last tick report shows in status

    def test_tick_records_github_errors(self):
        from relay.gh import GhError

        class BrokenGitHub(FakeGitHub):
            def list_prs(self, label=None, limit=50):
                raise GhError("gh pr list failed: HTTP 401")

        relay = Relay(self.cfg, BrokenGitHub(), runner=FakeRunner())
        self.assertIn("ERROR: tick stopped early", relay.tick())
        self.assertIn("HTTP 401", relay.last_tick())
        self.assertFalse(relay.tick_running())


if __name__ == "__main__":
    unittest.main()
