import io
import json
import tempfile
import unittest
from pathlib import Path

from relay.config import ConfigError, load_config
from relay.gh import checks_green, checks_state
from relay.mcp_server import serve
from relay.result import parse_build, parse_plan, parse_review
from relay.routing import (can_auto_merge, choose_builder, choose_reviewer, depends_on,
                           rework_round)

from .helpers import CONFIG, make_config

ROOT = Path(__file__).resolve().parents[1]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self.cfg = make_config(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()


class ConfigTests(TempDirCase):
    def test_example_config_loads(self):
        cfg = make_config(self.tmp, text=(ROOT / "relay.example.toml").read_text())
        self.assertEqual(cfg.by_size["S"], "copilot-cloud")
        self.assertTrue(cfg.agents["copilot-cloud"].is_cloud)
        self.assertEqual(cfg.agents["codex"].args["build"][:3],
                         ["exec", "--sandbox", "workspace-write"])

    def test_same_vendor_reviewer_rejected(self):
        bad = CONFIG.replace('codex = "claude"', 'codex = "codex"')
        with self.assertRaisesRegex(ConfigError, "different vendor"):
            make_config(self.tmp, text=bad)

    def test_cloud_reviewer_rejected(self):
        bad = CONFIG.replace('claude = "codex",', 'claude = "copilot-cloud",')
        with self.assertRaisesRegex(ConfigError, "cloud agent"):
            make_config(self.tmp, text=bad)

    def test_unknown_agent_rejected(self):
        with self.assertRaisesRegex(ConfigError, "gemini"):
            make_config(self.tmp, text=CONFIG.replace('L = "claude"', 'L = "gemini"'))

    def test_missing_config(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(self.tmp / "nope.toml")


class RoutingTests(TempDirCase):
    def test_routes_by_size(self):
        self.assertEqual(choose_builder(self.cfg, ["size:L"], {})[0], "claude")
        self.assertEqual(choose_builder(self.cfg, ["size:M"], {})[0], "codex")
        self.assertEqual(choose_builder(self.cfg, [], {})[0], "codex")  # default size M

    def test_falls_back_when_over_budget(self):
        agent, reason = choose_builder(self.cfg, ["size:M"], {"codex": {"runs": 10}})
        self.assertEqual(agent, "claude")
        self.assertIn("fell back", reason)

    def test_label_override_and_exhaustion(self):
        self.assertEqual(choose_builder(self.cfg, ["relay:agent:claude", "size:S"], {})[0],
                         "claude")
        usage = {"codex": {"runs": 10}, "claude": {"runs": 10}}
        self.assertIsNone(choose_builder(self.cfg, ["size:M"], usage)[0])

    def test_usd_cap(self):
        cfg = make_config(self.tmp, text=CONFIG.replace(
            '[agents.claude]\nkind = "claude"',
            '[agents.claude]\nkind = "claude"\nmax_usd_per_day = 5'))
        self.assertEqual(choose_builder(cfg, ["size:L"], {"claude": {"runs": 1, "usd": 5.0}})[0],
                         "codex")

    def test_reviewer_is_other_vendor(self):
        self.assertEqual(choose_reviewer(self.cfg, "codex", {})[0], "claude")
        self.assertEqual(choose_reviewer(self.cfg, "claude", {})[0], "codex")
        self.assertEqual(choose_reviewer(self.cfg, "copilot-cloud", {})[0], "claude")
        # preferred reviewer out of budget and no other vendor left -> nobody
        self.assertIsNone(choose_reviewer(self.cfg, "codex", {"claude": {"runs": 10}})[0])

    def test_auto_merge_rules(self):
        labels = ["relay:approved", "size:S"]
        self.assertTrue(can_auto_merge(self.cfg, labels, "low", True)[0])
        self.assertFalse(can_auto_merge(self.cfg, labels, "medium", True)[0])
        self.assertFalse(can_auto_merge(self.cfg, labels, "low", False)[0])
        self.assertFalse(can_auto_merge(self.cfg, ["relay:approved", "size:M"], "low", True)[0])
        self.assertFalse(can_auto_merge(self.cfg, ["size:S"], "low", True)[0])

    def test_depends_and_rework_parsing(self):
        self.assertEqual(depends_on("Part of #1\nDepends on: #3, #4 and #7"), [3, 4, 7])
        self.assertEqual(depends_on("no deps here"), [])
        self.assertEqual(rework_round(["rework:1", "rework:2", "x"]), 2)

    def test_checks_state(self):
        self.assertEqual(checks_state([]), "none")
        self.assertEqual(checks_state([{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}]), "green")
        self.assertEqual(checks_state([{"conclusion": "SUCCESS"}, {"status": "IN_PROGRESS"}]),
                         "pending")
        self.assertEqual(checks_state([{"conclusion": "FAILURE"}]), "failed")
        self.assertFalse(checks_green([], require_ci=True))
        self.assertTrue(checks_green([], require_ci=False))


class ResultParsingTests(unittest.TestCase):
    def test_parse_build_markers(self):
        text = ('lots of logs { not json }\nRELAY_RESULT\n{"status": "done", "summary": "ok", '
                '"risk": "medium", "tests_passed": true}\nEND_RELAY_RESULT\n')
        r = parse_build(text)
        self.assertEqual((r["status"], r["risk"], r["tests_passed"]), ("done", "medium", True))

    def test_parse_build_fenced_and_garbage(self):
        r = parse_build('```json\n{"status": "blocked", "open_questions": ["which db?"]}\n```')
        self.assertEqual(r["open_questions"], ["which db?"])
        r = parse_build("I did some stuff but forgot the block")
        self.assertEqual(r["status"], "failed")
        self.assertFalse(r["parsed"])
        self.assertEqual(parse_build('RELAY_RESULT\n{"status": "maybe"}\nEND_RELAY_RESULT')[
            "status"], "failed")

    def test_parse_review_never_approves_with_blockers(self):
        r = parse_review('RELAY_RESULT\n{"verdict": "approve", "blocking_issues": '
                         '["sql injection"], "risk": "low"}\nEND_RELAY_RESULT')
        self.assertEqual(r["verdict"], "request_changes")
        self.assertEqual(parse_review("garbage")["verdict"], "request_changes")
        self.assertEqual(parse_review('{"verdict": "approve", "risk": "weird"}')["risk"], "high")

    def test_parse_plan(self):
        p = parse_plan('RELAY_RESULT\n{"title": "T", "tasks": [{"title": "a", "size": "XL"}, '
                       '{"size": "S"}, {"title": "b", "depends_on": [0, "x"]}]}\nEND_RELAY_RESULT')
        self.assertEqual([t["title"] for t in p["tasks"]], ["a", "b"])
        self.assertEqual(p["tasks"][0]["size"], "M")
        self.assertEqual(p["tasks"][1]["depends_on"], [0])


class StubRelay:
    def status(self):
        return "all quiet"

    def plan(self, idea):
        return f"planned {idea}"

    def approve(self, n):
        raise RuntimeError("boom")

    def set_stop(self, on):
        return "ok"

    def stopped(self):
        return True


class McpTests(unittest.TestCase):
    def test_round_trip(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "relay_plan", "arguments": {"idea": "login"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "relay_approve", "arguments": {"issue": 3}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"},
        ]
        out = io.StringIO()
        stdin = io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\nnot json\n")
        serve(StubRelay(), stdin, out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r.get("id") for r in replies], [1, 2, 3, 4, 5, None])
        self.assertEqual(replies[0]["result"]["capabilities"], {"tools": {}})
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertTrue({"relay_status", "relay_tick", "relay_plan"} <= names)
        self.assertEqual(replies[2]["result"]["content"][0]["text"], "planned login")
        self.assertTrue(replies[3]["result"]["isError"])
        self.assertEqual(replies[4]["error"]["code"], -32601)
        self.assertEqual(replies[5]["error"]["code"], -32700)

    def test_tick_tool_respects_pause(self):
        out = io.StringIO()
        msg = {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
               "params": {"name": "relay_tick", "arguments": {}}}
        serve(StubRelay(), io.StringIO(json.dumps(msg) + "\n"), out)
        self.assertIn("paused", json.loads(out.getvalue())["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
