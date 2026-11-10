"""Isolated rewrite adapter tests. No real provider process is invoked."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.rewrite import RewriteError, capabilities, run_rewrite


REPORT = {"critique": ["Require explicit acceptance criteria."],
          "revised_prompt": "Implement the scoped operation and verify the acceptance criteria.",
          "open_questions": [], "limitations": ["Research was supplied, not independently fetched."]}
SECRET = "test-api-key-do-not-display"


def completed(envelope=None, **kwargs):
    if envelope is None:
        envelope = {"type": "result", "subtype": "success", "is_error": False,
                    "structured_output": REPORT}
    return subprocess.CompletedProcess([], kwargs.get("returncode", 0),
                                       kwargs.get("stdout", json.dumps(envelope)),
                                       kwargs.get("stderr", ""))


class RewriteTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET,
                                         "PATH": "test-path", "USERPROFILE": "test-home"}, clear=True)
        self.env.start()
        self.which = patch("relay.rewrite.shutil.which", return_value="/trusted/claude")
        self.which_mock = self.which.start()
        self.run = patch("relay.rewrite.subprocess.run", return_value=completed())
        self.run_mock = self.run.start()
        self.addCleanup(self.run.stop)
        self.addCleanup(self.which.stop)
        self.addCleanup(self.env.stop)

    def test_passes_payload_only_on_stdin_without_tools_or_project_context(self):
        payload = {"draft_prompt": "PRIVATE --mcp-config evil.json $(echo bad)",
                   "command": "evil", "model": "evil",
                   "env": {"GH_TOKEN": "evil", "DISABLE_UPDATES": "0"}}

        def inspect(args, **kwargs):
            self.assertEqual(json.loads(kwargs["input"]), payload)
            self.assertNotIn("PRIVATE", " ".join(args))
            self.assertIn("--bare", args)
            self.assertIn("-p", args)
            self.assertEqual(args[args.index("--tools") + 1], "")
            self.assertEqual(args[args.index("--disallowedTools") + 1], "mcp__*")
            self.assertIn("--strict-mcp-config", args)
            self.assertEqual(json.loads(args[args.index("--mcp-config") + 1]), {"mcpServers": {}})
            self.assertIn("--no-session-persistence", args)
            self.assertEqual(args[args.index("--setting-sources") + 1], "")
            self.assertEqual(args[args.index("--output-format") + 1], "json")
            schema = json.loads(args[args.index("--json-schema") + 1])
            self.assertFalse(schema["additionalProperties"])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["timeout"], 180)
            work = Path(kwargs["cwd"])
            self.assertTrue(work.is_dir())
            self.assertEqual(list(work.iterdir()), [])
            self.assertNotEqual(work, Path.cwd())
            self.assertTrue(Path(kwargs["env"]["CLAUDE_CONFIG_DIR"]).is_dir())
            self.assertEqual(kwargs["env"]["DISABLE_UPDATES"], "1")
            return completed()

        self.run_mock.side_effect = inspect
        result = run_rewrite(payload)
        self.assertEqual(result, {**REPORT, "provider": "anthropic", "tool": "claude-cli",
                                  "model": "unreported"})
        self.assertFalse(Path(self.run_mock.call_args.kwargs["cwd"]).exists())

    def test_child_environment_excludes_other_credentials_and_startup_overrides(self):
        os.environ.update({"GH_TOKEN": "private-gh", "OPENAI_API_KEY": "private-openai",
                           "ANTHROPIC_AUTH_TOKEN": "private-auth", "NODE_OPTIONS": "--require evil",
                           "CLAUDE_CODE_OAUTH_TOKEN": "private-oauth", "CLAUDE_CONFIG_DIR": "evil",
                           "ANTHROPIC_BASE_URL": "https://evil.invalid", "MCP_TIMEOUT": "1",
                           "DISABLE_UPDATES": "0",
                           "RELAY_CLAUDE_COMMAND": "trusted-cli", "RELAY_CLAUDE_MODEL": "sonnet"})
        result = run_rewrite({"prompt": "draft"}, timeout_s=30)
        self.which_mock.assert_called_once_with("trusted-cli")
        args = self.run_mock.call_args.args[0]
        env = self.run_mock.call_args.kwargs["env"]
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        self.assertEqual(result["model"], "sonnet")
        self.assertEqual(env["ANTHROPIC_API_KEY"], SECRET)
        self.assertEqual(env["PATH"], "test-path")
        self.assertEqual(env["USERPROFILE"], "test-home")
        self.assertEqual(set(env), {"ANTHROPIC_API_KEY", "PATH", "USERPROFILE",
                                    "CLAUDE_CONFIG_DIR", "DISABLE_UPDATES"})
        self.assertEqual(env["DISABLE_UPDATES"], "1")
        self.assertNotEqual(env["CLAUDE_CONFIG_DIR"], "evil")

    def test_reports_prerequisites_without_calling_provider(self):
        result = capabilities()
        self.assertTrue(result["ready"])
        self.assertTrue(result["installed"])
        self.assertTrue(result["api_key_configured"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn("/trusted", json.dumps(result))
        self.run_mock.assert_not_called()

    def test_local_model_configuration_cannot_expose_paths_or_credentials(self):
        for model in ("C:/private/model", "sk-ant-" + "a" * 30, SECRET):
            with self.subTest(model_type="invalid"), patch.dict(os.environ, {"RELAY_CLAUDE_MODEL": model}):
                result = capabilities()
                self.assertFalse(result["ready"])
                self.assertNotIn(model, json.dumps(result))
                with self.assertRaises(RewriteError):
                    run_rewrite({})
        self.run_mock.assert_not_called()

    def test_non_ascii_input_uses_same_character_limit_as_saved_handoff(self):
        payload = {"research": "\u7814" * 100000}
        run_rewrite(payload)
        self.assertEqual(json.loads(self.run_mock.call_args.kwargs["input"]), payload)

    def test_missing_cli_and_missing_key_are_actionable_and_do_not_run(self):
        self.which_mock.return_value = None
        self.assertFalse(capabilities()["ready"])
        with self.assertRaisesRegex(RewriteError, "official Claude CLI"):
            run_rewrite({})
        self.which_mock.return_value = "/trusted/claude"
        os.environ.pop("ANTHROPIC_API_KEY")
        self.assertFalse(capabilities()["ready"])
        with self.assertRaisesRegex(RewriteError, "ANTHROPIC_API_KEY is required"):
            run_rewrite({})
        self.run_mock.assert_not_called()

    def test_rejects_invalid_input_and_configuration(self):
        for payload in ([], {"bad": float("nan")}, {"bad": object()},
                        {"bad": "\ud800"}, {"large": "x" * 200001}):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(RewriteError):
                    run_rewrite(payload)
        for timeout in (0, -1, 901, True, 1.5):
            with self.subTest(timeout=timeout):
                with self.assertRaises(RewriteError):
                    run_rewrite({}, timeout_s=timeout)
        os.environ["RELAY_CLAUDE_MODEL"] = "--mcp-config evil"
        with self.assertRaisesRegex(RewriteError, "model identifier"):
            run_rewrite({})
        self.assertFalse(capabilities()["ready"])
        os.environ.pop("RELAY_CLAUDE_MODEL")
        os.environ["RELAY_CLAUDE_COMMAND"] = "bad\ncommand"
        with self.assertRaisesRegex(RewriteError, "one executable"):
            run_rewrite({})
        self.run_mock.assert_not_called()

    def test_fails_closed_for_missing_malformed_or_unsuccessful_output(self):
        base = {"type": "result", "subtype": "success", "is_error": False,
                "structured_output": REPORT}
        cases = ["not-json", "[]", "{}", json.dumps({**base, "is_error": True}),
                 json.dumps({**base, "subtype": "error_max_turns"}),
                 json.dumps({**base, "permission_denials": [{"tool": "Bash"}]}),
                 json.dumps({**base, "mcp_server_errors": [{"name": "server"}]}),
                 json.dumps({k: v for k, v in base.items() if k != "structured_output"}),
                 json.dumps({**base, "structured_output": {**REPORT, "revised_prompt": " "}}),
                 json.dumps({**base, "structured_output": {**REPORT, "critique": "not a list"}}),
                 json.dumps({**base, "structured_output": {**REPORT, "critique": [False]}}),
                 json.dumps({**base, "structured_output": {**REPORT, "critique": ["x" * 12001]}}),
                 json.dumps({**base, "structured_output": {**REPORT, "critique": ["x" * 10000] * 20}}),
                 json.dumps({**base, "structured_output": {**REPORT, "extra": "not permitted"}}),
                 '{"type":"result","type":"other"}',
                 '{"type":"result","cost":NaN}', "x" * 2000001]
        for stdout in cases:
            with self.subTest(output=stdout[:60]):
                self.run_mock.return_value = completed(stdout=stdout)
                with self.assertRaises(RewriteError):
                    run_rewrite({})

    def test_failures_do_not_expose_provider_output_or_exception_details(self):
        sensitive = SECRET + " PRIVATE-PROMPT"
        failures = [subprocess.TimeoutExpired(sensitive, 1, output=sensitive, stderr=sensitive),
                    OSError(sensitive), ValueError(sensitive)]
        for failure in failures:
            with self.subTest(error=type(failure).__name__):
                self.run_mock.side_effect = failure
                with self.assertRaises(RewriteError) as caught:
                    run_rewrite({"draft": sensitive})
                self.assertNotIn(sensitive, str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
        self.run_mock.side_effect = None
        self.run_mock.return_value = completed(returncode=9, stdout=sensitive, stderr=sensitive)
        with self.assertRaises(RewriteError) as caught:
            run_rewrite({"draft": sensitive})
        self.assertNotIn(sensitive, str(caught.exception))
        self.run_mock.return_value = completed({"type": "result", "subtype": "error",
                                                "is_error": True, "result": sensitive})
        with self.assertRaises(RewriteError) as caught:
            run_rewrite({})
        self.assertNotIn(sensitive, str(caught.exception))

    def test_only_allowlisted_numeric_usage_is_returned(self):
        self.run_mock.return_value = completed({"type": "result", "subtype": "success",
                                               "is_error": False, "structured_output": REPORT,
                                               "usage": {"input_tokens": 10, "output_tokens": 5,
                                                         "cache_read_input_tokens": True,
                                                         "cache_creation_input_tokens": -1,
                                                         "private": SECRET},
                                               "total_cost_usd": 0.002, "session_id": SECRET})
        result = run_rewrite({})
        self.assertEqual(result["usage"], {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(result["total_cost_usd"], 0.002)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_actual_bridge_worker_accepts_and_persists_validated_provider_report(self):
        from relay.bridge import run_job
        from relay.jobs import JobStore

        with tempfile.TemporaryDirectory(dir=Path.cwd(), ignore_cleanup_errors=True) as tmp:
            store = JobStore(Path(tmp))
            payload = {"objective": "Count words", "research": "Whitespace separates words.",
                       "rough_prompt": "Create a word counter.", "sources": ["https://example.com/spec"]}
            job = store.submit(payload)
            self.assertTrue(run_job(store, job["job_id"]))
            persisted = store.get(job["job_id"])
            self.assertEqual(persisted["status"], "completed")
            self.assertEqual(persisted["input"]["sources"], payload["sources"])
            self.assertEqual(persisted["result"]["revised_prompt"], REPORT["revised_prompt"])
            self.assertEqual(persisted["result"]["provider"], "anthropic")
            self.assertEqual(persisted["result"]["model"], "unreported")
            self.assertFalse(run_job(store, job["job_id"]))
            self.run_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
