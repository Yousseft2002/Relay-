"""Runs the real subprocess adapters against tiny fake CLIs written in Python."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from relay.agents import AgentUnavailable, run_agent
from relay.config import AgentConfig, DEFAULT_ARGS

FAKE_CLAUDE = textwrap.dedent('''
    import json, sys
    prompt = sys.stdin.read()
    assert "-p" in sys.argv and "--output-format" in sys.argv
    print(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.42,
                      "session_id": "abc",
                      "result": "echo: " + prompt.strip() + "\\nRELAY_RESULT\\n{\\"status\\": \\"done\\"}\\nEND_RELAY_RESULT"}))
''')

FAKE_CODEX = textwrap.dedent('''
    import json, sys
    prompt = sys.stdin.read()
    args = sys.argv[1:]
    assert args[0] == "exec" and args[-1] == "-"
    out = args[args.index("-o") + 1]
    open(out, "w").write("final: " + prompt.strip())
    print(json.dumps({"type": "thread.started"}))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}}))
''')

FAKE_FAIL = "import sys; sys.stdin.read(); print('nope', file=sys.stderr); sys.exit(3)"


def agent(kind, script_path):
    return AgentConfig(name=kind, kind=kind, command=[sys.executable, str(script_path)],
                       args={m: list(DEFAULT_ARGS[kind][m]) for m in ("build", "review", "plan")},
                       timeout_min=1)


class AgentAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def script(self, name, body):
        path = self.tmp / name
        path.write_text(body)
        return path

    def test_claude_adapter_reads_json_and_cost(self):
        out = run_agent(agent("claude", self.script("c.py", FAKE_CLAUDE)), "build",
                        "build the thing", self.tmp)
        self.assertTrue(out.ok)
        self.assertIn("echo: build the thing", out.text)
        self.assertAlmostEqual(out.usd, 0.42)

    def test_codex_adapter_reads_last_message_and_tokens(self):
        out = run_agent(agent("codex", self.script("x.py", FAKE_CODEX)), "review",
                        "review this", self.tmp)
        self.assertTrue(out.ok)
        self.assertEqual(out.text, "final: review this")
        self.assertEqual(out.tokens, 150)

    def test_failure_reports_stderr(self):
        out = run_agent(agent("copilot", self.script("f.py", FAKE_FAIL)), "build", "x", self.tmp)
        self.assertFalse(out.ok)
        self.assertEqual(out.returncode, 3)
        self.assertIn("nope", out.error)

    def test_missing_cli_and_cloud(self):
        missing = AgentConfig(name="codex", kind="codex", command=["definitely-not-installed"],
                              args={m: [] for m in ("build", "review", "plan")})
        with self.assertRaises(AgentUnavailable):
            run_agent(missing, "build", "x", self.tmp)
        cloud = AgentConfig(name="cc", kind="copilot-cloud", command=[],
                            args={m: [] for m in ("build", "review", "plan")})
        with self.assertRaises(AgentUnavailable):
            run_agent(cloud, "build", "x", self.tmp)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_smoke_runs_real_fake_clis(self):
        from relay.smoke import smoke

        from .helpers import CONFIG, make_config
        (self.tmp / "c.py").write_text(FAKE_CLAUDE.replace(
            '"echo: " + prompt.strip() + "\\nRELAY_RESULT\\n{\\"status\\": \\"done\\"}\\nEND_RELAY_RESULT"',
            'prompt'))
        (self.tmp / "x.py").write_text(FAKE_CODEX.replace('"final: " + prompt.strip()', 'prompt'))
        text = CONFIG.replace('[agents.claude]\nkind = "claude"',
                              f'[agents.claude]\nkind = "claude"\ncommand = [\'{sys.executable}\', \'{self.tmp / "c.py"}\']')
        text = text.replace('[agents.codex]\nkind = "codex"',
                            f'[agents.codex]\nkind = "codex"\ncommand = [\'{sys.executable}\', \'{self.tmp / "x.py"}\']')
        cfg = make_config(self.tmp, text=text)
        report = smoke(cfg)
        self.assertIn("ok       claude (review flags)", report)
        self.assertIn("ok       codex (build flags)", report)
        self.assertIn("skip     copilot-cloud", report)
        self.assertIn("All agents ready.", report)

    def test_smoke_reports_failures_with_hints(self):
        from relay.smoke import smoke

        from .helpers import CONFIG, make_config
        (self.tmp / "f.py").write_text(FAKE_FAIL)
        text = CONFIG.replace('[agents.codex]\nkind = "codex"',
                              f'[agents.codex]\nkind = "codex"\ncommand = [\'{sys.executable}\', \'{self.tmp / "f.py"}\']')
        report = smoke(make_config(self.tmp, text=text), only=["codex"])
        self.assertIn("FAIL     codex (review flags)", report)
        self.assertIn("hint: Run `codex` once", report)
        self.assertIn("check(s) failed", report)


if __name__ == "__main__":
    unittest.main()
