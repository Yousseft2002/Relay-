import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.bridge import Bridge, handle, run_job, serve
from relay.rewrite import RewriteError


PAYLOAD = {"objective": "Improve a retry task", "research": "Retries need stable keys.",
           "rough_prompt": "Add retries", "sources": ["https://example.com/spec"],
           "acceptance_criteria": ["One logical request produces one payment."]}
REPORT = {"critique": ["Specify idempotency"], "revised_prompt": "Use stable keys.",
          "open_questions": [], "limitations": ["Sources supplied; not fetched."]}
ROOT = Path(__file__).resolve().parents[1]
MODERN_META = {"_meta": {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "bridge-test-client", "version": "1.0.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = Bridge(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_surface_cannot_build_or_call_provider(self):
        tools = self.bridge.tools()
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"relay_health", "relay_submit_research",
                                 "relay_job_status", "relay_job_result"})
        annotations = {t["name"]: t["annotations"]["readOnlyHint"] for t in tools}
        self.assertTrue(annotations["relay_health"])
        self.assertFalse(annotations["relay_submit_research"])
        with self.assertRaises(ValueError):
            self.bridge.call("relay_start_rewrite", {"job_id": "0" * 32})

    def test_modern_discovery_then_list_preserves_tool_gating_without_provider_calls(self):
        for enabled, count in ((False, 4), (True, 5)):
            with self.subTest(rewrite_enabled=enabled):
                bridge = Bridge(self.root, allow_rewrite=enabled)
                requests = [
                    {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": MODERN_META},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": MODERN_META},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {**MODERN_META, "name": "relay_health", "arguments": {}}},
                ]
                output = io.StringIO()
                with patch("relay.bridge.capabilities", return_value={"ready": False}) as local_readiness, \
                        patch("relay.bridge.subprocess.Popen") as worker:
                    serve(bridge, io.StringIO("\n".join(json.dumps(item) for item in requests) + "\n"), output)
                local_readiness.assert_called_once_with()
                worker.assert_not_called()
                discovery, listing, health_reply = [json.loads(line)["result"]
                                                    for line in output.getvalue().splitlines()]
                self.assertEqual(discovery["resultType"], "complete")
                self.assertEqual(discovery["supportedVersions"],
                                 ["2026-07-28", "2025-06-18", "2025-03-26", "2024-11-05"])
                self.assertEqual(discovery["capabilities"], {"tools": {}})
                self.assertEqual(discovery["_meta"]["io.modelcontextprotocol/serverInfo"],
                                 {"name": "relay-research-bridge", "version": "0.1.1"})
                self.assertIn("untrusted", discovery["instructions"])
                self.assertNotIn("serverInfo", discovery)
                self.assertNotIn("tools", discovery)
                self.assertEqual(len(listing["tools"]), count)
                self.assertEqual("relay_start_rewrite" in {tool["name"] for tool in listing["tools"]}, enabled)
                health = health_reply["structuredContent"]
                self.assertEqual(health["server_version"],
                                 discovery["_meta"]["io.modelcontextprotocol/serverInfo"]["version"])
                self.assertEqual(health["advertised_tools"], [tool["name"] for tool in listing["tools"]])
                self.assertEqual(health["rewrite_enabled"], enabled)

    def test_legacy_initialization_keeps_negotiation_and_identity(self):
        for requested, negotiated in (("2025-06-18", "2025-06-18"),
                                      ("2024-11-05", "2024-11-05"),
                                      ("made-up", "2025-06-18")):
            with self.subTest(requested=requested):
                result = handle(self.bridge, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                              "params": {"protocolVersion": requested}})["result"]
                self.assertEqual(result["protocolVersion"], negotiated)
                self.assertEqual(result["capabilities"], {"tools": {}})
                self.assertEqual(result["serverInfo"],
                                 {"name": "relay-research-bridge", "version": "0.1.1"})
                self.assertNotIn("supportedVersions", result)
                discovery = handle(self.bridge, {"jsonrpc": "2.0", "id": 2,
                                                 "method": "server/discover", "params": MODERN_META})
                self.assertEqual(result["instructions"], discovery["result"]["instructions"])

    def test_discovery_metadata_validation_and_version_negotiation(self):
        for params in (None, [], {}, {"_meta": []}, {"_meta": {}},
                       {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
                       {"_meta": {"io.modelcontextprotocol/protocolVersion": " ",
                                  "io.modelcontextprotocol/clientCapabilities": {}}},
                       {"_meta": {**MODERN_META["_meta"], "io.modelcontextprotocol/clientCapabilities": []}},
                       {"_meta": {**MODERN_META["_meta"], "io.modelcontextprotocol/clientInfo": None}},
                       {"_meta": {**MODERN_META["_meta"], "io.modelcontextprotocol/clientInfo": {"name": "client"}}}):
            with self.subTest(params=params):
                reply = handle(self.bridge, {"jsonrpc": "2.0", "id": 1,
                                             "method": "server/discover", "params": params})
                self.assertEqual(reply["error"]["code"], -32602)
        minimal = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2099-01-01",
                             "io.modelcontextprotocol/clientCapabilities": {}}}
        reply = handle(self.bridge, {"jsonrpc": "2.0", "id": 2,
                                     "method": "server/discover", "params": minimal})
        self.assertIn("2026-07-28", reply["result"]["supportedVersions"])

    def test_source_launcher_discovers_modern_tools_without_legacy_initialize(self):
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": MODERN_META},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": MODERN_META},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {**MODERN_META, "name": "relay_health", "arguments": {}}}]
        # Keep provider credentials out of this protocol-only subprocess check.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
                                  "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE"}}
        for enabled, expected_count in ((False, 4), (True, 5)):
            with self.subTest(rewrite_enabled=enabled):
                command = [sys.executable, str(ROOT / "bridge_server.py"),
                           "--state-dir", str(self.root / ("enabled" if enabled else "disabled"))]
                if enabled:
                    command.append("--allow-rewrite")
                process = subprocess.run(command, cwd=self.root, env=env,
                                         input="\n".join(json.dumps(item) for item in messages) + "\n",
                                         text=True, encoding="utf-8", capture_output=True,
                                         timeout=15, check=True)
                self.assertEqual(process.stderr, "")
                discovery, listing, health_reply = [json.loads(line)["result"]
                                                    for line in process.stdout.splitlines()]
                self.assertEqual(discovery["resultType"], "complete")
                self.assertEqual(len(listing["tools"]), expected_count)
                health = health_reply["structuredContent"]
                self.assertEqual(health["server_version"], "0.1.1")
                self.assertEqual(health["advertised_tools"], [tool["name"] for tool in listing["tools"]])
                self.assertFalse(health["rewrite"]["api_key_configured"])

    def test_round_trip_preserves_research_across_restart(self):
        job = self.bridge.call("relay_submit_research", {**PAYLOAD, "request_id": "test-1"})
        second = Bridge(self.root)
        duplicate = second.call("relay_submit_research", {**PAYLOAD, "request_id": "test-1"})
        self.assertEqual(job["job_id"], duplicate["job_id"])
        args = {"job_id": job["job_id"]}
        with self.assertRaisesRegex(ValueError, "No completed"):
            second.call("relay_job_result", args)
        called = []

        def rewrite(payload, timeout_s):
            called.append(payload)
            self.assertEqual(timeout_s, 180)
            return REPORT

        self.assertTrue(run_job(second.store, job["job_id"], runner=rewrite))
        self.assertFalse(run_job(second.store, job["job_id"], runner=rewrite))
        self.assertEqual(len(called), 1)
        self.assertEqual(called[0], PAYLOAD)
        result = Bridge(self.root).call("relay_job_result", args)
        self.assertEqual(result["input"]["sources"], PAYLOAD["sources"])
        self.assertEqual(result["result"], REPORT)
        self.assertEqual(result["status"], "completed")

    def test_worker_failure_is_explicit_and_does_not_leak(self):
        job = self.bridge.store.submit(PAYLOAD)

        def explode(*args, **kwargs):
            raise RuntimeError("secret-provider-diagnostic")

        self.assertFalse(run_job(self.bridge.store, job["job_id"], runner=explode))
        stored = self.bridge.store.get(job["job_id"])
        self.assertEqual(stored["status"], "failed")
        self.assertNotIn("secret-provider-diagnostic", stored["error"])

    def test_provider_readiness_blocks_launch(self):
        bridge = Bridge(self.root, allow_rewrite=True)
        job = bridge.store.submit(PAYLOAD)
        with patch("relay.bridge.capabilities", return_value={"ready": False, "reason": "Configure Claude"}), \
                patch.object(bridge, "_launch") as launch:
            with self.assertRaisesRegex(ValueError, "Configure Claude"):
                bridge.call("relay_start_rewrite", {"job_id": job["job_id"]})
            launch.assert_not_called()
        self.assertEqual(bridge.store.get(job["job_id"])["status"], "submitted")

    def test_enabled_launch_is_async_and_uses_only_saved_job(self):
        bridge = Bridge(self.root, allow_rewrite=True)
        job = bridge.store.submit(PAYLOAD)
        with patch("relay.bridge.capabilities", return_value={"ready": True}), \
                patch("relay.bridge.subprocess.Popen") as launch:
            result = bridge.call("relay_start_rewrite", {"job_id": job["job_id"]})
            self.assertTrue(result["worker_started"])
            command = launch.call_args.args[0]
            self.assertIn(job["job_id"], command)
            self.assertNotIn(PAYLOAD["rough_prompt"], " ".join(command))
            self.assertEqual(launch.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_explicit_provider_error_is_reported(self):
        job = self.bridge.store.submit(PAYLOAD)

        def unavailable(*args, **kwargs):
            raise RewriteError("Claude API credentials are not configured.")

        self.assertFalse(run_job(self.bridge.store, job["job_id"], runner=unavailable))
        self.assertIn("not configured", self.bridge.store.get(job["job_id"])["error"])

    def test_stdio_errors_do_not_break_next_request(self):
        messages = ["not-json", "[]", json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "made-up"}}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "relay_submit_research", "arguments": PAYLOAD}})]
        output = io.StringIO()
        serve(self.bridge, io.StringIO("\n".join(messages)), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 4)
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["error"]["code"], -32600)
        self.assertEqual(replies[2]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[3]["result"]["structuredContent"]["status"], "submitted")

    def test_reject_unexpected_fields_and_bad_ids(self):
        for name, args in [("relay_health", {"shell": "run"}),
                           ("relay_job_status", {"job_id": "../../credentials"}),
                           ("relay_submit_research", {**PAYLOAD, "command": "run"})]:
            with self.assertRaises(ValueError):
                self.bridge.call(name, args)

    def test_fresh_process_can_submit_then_another_reads_status(self):
        def exchange(message):
            proc = subprocess.run([sys.executable, "-m", "relay.bridge", "--state-dir", str(self.root)],
                                  cwd=ROOT, input=json.dumps(message) + "\n", text=True,
                                  capture_output=True, timeout=15, check=True)
            self.assertEqual(proc.stderr, "")
            return json.loads(proc.stdout)["result"]["structuredContent"]

        job = exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "relay_submit_research", "arguments": PAYLOAD}})
        result = exchange({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "relay_job_status", "arguments": {"job_id": job["job_id"]}}})
        self.assertEqual(result["job_id"], job["job_id"])
        self.assertEqual(result["status"], "submitted")

    def test_source_launcher_works_outside_checkout(self):
        proc = subprocess.run([sys.executable, str(ROOT / "bridge_server.py"),
                               "--state-dir", str(self.root), "health"],
                              cwd=self.root, capture_output=True, text=True, timeout=15,
                              check=True)
        self.assertEqual(json.loads(proc.stdout)["status"], "ok")
        self.assertEqual(proc.stderr, "")

    def test_unicode_research_and_result_fit_transport_limits(self):
        payload = {**PAYLOAD, "research": "\u7814" * 100000,
                   "rough_prompt": "\u7a76" * 80000}
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "relay_submit_research", "arguments": payload}}
        output = io.StringIO()
        serve(self.bridge, io.StringIO(json.dumps(message) + "\n"), output)
        job = json.loads(output.getvalue())["result"]["structuredContent"]
        self.assertEqual(job["status"], "submitted")
        report = {**REPORT, "revised_prompt": "\u65b0" * 90000}
        self.assertTrue(run_job(self.bridge.store, job["job_id"], runner=lambda *a, **k: report))
        message["params"] = {"name": "relay_job_result", "arguments": {"job_id": job["job_id"]}}
        output = io.StringIO()
        serve(self.bridge, io.StringIO(json.dumps(message) + "\n"), output)
        response = json.loads(output.getvalue())
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["result"], report)

    def test_deep_json_does_not_terminate_stdio_connection(self):
        depth = sys.getrecursionlimit() + 1000
        malformed = "[" * depth + "0" + "]" * depth
        ping = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        output = io.StringIO()
        serve(self.bridge, io.StringIO(malformed + "\n" + ping + "\n"), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertIn(replies[0]["error"]["code"], (-32700, -32600))
        self.assertEqual(replies[1]["id"], 2)

    def test_oversized_json_integer_does_not_terminate_connection(self):
        request = '{"jsonrpc":"2.0","method":"ping","id":' + "9" * 10000 + "}"
        ping = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        output = io.StringIO()
        serve(self.bridge, io.StringIO(request + "\n" + ping + "\n"), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["id"], 3)

    def test_process_stdio_is_utf8_even_when_parent_locale_is_ascii(self):
        payload = {**PAYLOAD, "research": "\u7814\u7a76 \u2014 caf\u00e9"}
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "relay_submit_research", "arguments": payload}}
        env = {**os.environ, "PYTHONIOENCODING": "ascii"}
        proc = subprocess.run([sys.executable, str(ROOT / "bridge_server.py"),
                               "--state-dir", str(self.root)], cwd=self.root, env=env,
                              input=(json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"),
                              capture_output=True, timeout=15, check=True)
        reply = json.loads(proc.stdout.decode("utf-8"))
        job_id = reply["result"]["structuredContent"]["job_id"]
        self.assertEqual(self.bridge.store.get(job_id)["input"]["research"], payload["research"])


if __name__ == "__main__":
    unittest.main()
