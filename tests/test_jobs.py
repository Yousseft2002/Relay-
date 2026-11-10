"""Persistent handoffs, concurrency and fail-closed job transitions."""
import hashlib
import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.jobs import JobStore


def _claim_worker(root, job_id, start, results):
    store = JobStore(Path(root))
    start.wait(10)
    results.put(store.claim(job_id))


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = JobStore(self.root)
        self.payload = {"objective": "Implement a word counter", "research": "Count whitespace-separated words.",
                        "rough_prompt": "Add word_count(text), covering empty input."}

    def test_persists_input_hash_and_result_across_restarts(self):
        job = self.store.submit(self.payload)
        self.assertEqual(job["status"], "submitted")
        self.assertTrue(job["created_at"].endswith("Z"))
        self.assertEqual(job["input"]["sources"], [])
        encoded = json.dumps(job["input"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(job["input_hash"], hashlib.sha256(encoded.encode()).hexdigest())
        restarted = JobStore(self.root)
        self.assertEqual(restarted.get(job["job_id"]), job)
        self.assertTrue(restarted.claim(job["job_id"]))
        report = {"revised_prompt": "Validated prompt", "security": {"verdict": "pass"}}
        self.assertTrue(restarted.complete(job["job_id"], job["input_hash"], report))
        self.assertEqual(JobStore(self.root).get(job["job_id"])["result"], report)

    def test_request_key_is_idempotent_and_rejects_changed_input(self):
        job = self.store.submit(self.payload, "request-1")
        explicit_defaults = {**self.payload, "sources": [], "acceptance_criteria": []}
        repeated = JobStore(self.root).submit(explicit_defaults, "request-1")
        self.assertEqual(job, repeated)
        with self.assertRaises(ValueError):
            self.store.submit({**self.payload, "rough_prompt": "Different prompt"}, "request-1")
        self.assertNotEqual(job["job_id"], self.store.submit(self.payload)["job_id"])

    def test_claim_has_exactly_one_winner_across_processes(self):
        job = self.store.submit(self.payload)
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Event(), ctx.Queue()
        workers = [ctx.Process(target=_claim_worker,
                               args=(str(self.root), job["job_id"], start, results)) for _ in range(3)]
        try:
            for worker in workers:
                worker.start()
            start.set()
            self.assertEqual(sorted(results.get(timeout=20) for _ in workers), [False, False, True])
            for worker in workers:
                worker.join(timeout=20)
                self.assertEqual(worker.exitcode, 0)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=5)
            results.close()
            results.join_thread()

    def test_expiry_persists_and_never_requeues(self):
        with patch("relay.jobs.time.time", return_value=1000):
            job = self.store.submit(self.payload, "expired")
            self.assertTrue(self.store.claim(job["job_id"], timeout_s=1))
        with patch("relay.jobs.time.time", return_value=1001):
            expired = self.store.get(job["job_id"])
            self.assertEqual(expired["status"], "failed")
            self.assertIn("deadline expired", expired["error"])
            self.assertFalse(self.store.claim(job["job_id"]))
            self.assertFalse(self.store.complete(job["job_id"], job["input_hash"], {"ok": True}))
            self.assertFalse(self.store.fail(job["job_id"], "Late provider failure"))
            self.assertEqual(self.store.submit(self.payload, "expired"), expired)
        self.assertEqual(JobStore(self.root).get(job["job_id"]), expired)

    def test_completion_itself_expires_late_work(self):
        with patch("relay.jobs.time.time", return_value=1000):
            job = self.store.submit(self.payload)
            self.store.claim(job["job_id"], 5)
        with patch("relay.jobs.time.time", return_value=1006):
            self.assertFalse(self.store.complete(job["job_id"], job["input_hash"], {"ok": True}))
            self.assertIsNone(self.store.get(job["job_id"])["result"])

    def test_results_require_running_job_correct_hash_and_one_completion(self):
        job = self.store.submit(self.payload)
        self.assertFalse(self.store.complete(job["job_id"], job["input_hash"], {"ok": True}))
        self.store.claim(job["job_id"])
        self.assertFalse(self.store.complete(job["job_id"], "0" * 64, {"ok": True}))
        self.assertTrue(self.store.complete(job["job_id"], job["input_hash"], {"ok": True}))
        self.assertFalse(self.store.complete(job["job_id"], job["input_hash"], {"ok": False}))
        self.assertFalse(self.store.fail(job["job_id"], "Cannot overwrite success"))
        self.assertEqual(self.store.get(job["job_id"])["result"], {"ok": True})

    def test_failure_is_terminal(self):
        job = self.store.submit(self.payload)
        self.assertTrue(self.store.fail(job["job_id"], "Provider unavailable."))
        self.assertFalse(self.store.claim(job["job_id"]))
        self.assertFalse(self.store.fail(job["job_id"], "Second failure"))
        self.assertEqual(self.store.get(job["job_id"])["error"], "Provider unavailable.")

    def test_rejects_malformed_or_unbounded_input(self):
        bad_inputs = [None, [], {}, {**self.payload, "extra": "no"},
                      {**self.payload, "objective": " "}, {**self.payload, "research": 42},
                      {**self.payload, "rough_prompt": "\x00"},
                      {**self.payload, "rough_prompt": "\ud800"},
                      {**self.payload, "objective": "x" * 8001},
                      {**self.payload, "sources": "not a list"},
                      {**self.payload, "sources": ["x"] * 101},
                      {**self.payload, "sources": [3]},
                      {**self.payload, "acceptance_criteria": [""]},
                      {**self.payload, "research": "r" * 127_000, "rough_prompt": "p" * 95_000}]
        for payload in bad_inputs:
            with self.subTest(payload_type=type(payload).__name__), self.assertRaises(ValueError):
                self.store.submit(payload)
        for request_id in ("", "x" * 129, "a/b", 42, "key\n"):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                self.store.submit(self.payload, request_id)

    def test_rejects_obvious_credentials_without_echoing_them(self):
        secret = "sk-proj-" + "a" * 40
        with self.assertRaises(ValueError) as exc:
            self.store.submit({**self.payload, "research": secret})
        self.assertNotIn(secret, str(exc.exception))
        with self.assertRaises(ValueError):
            self.store.submit({**self.payload, "rough_prompt": "-----BEGIN PRIVATE KEY-----"})
        job = self.store.submit(self.payload)
        self.store.claim(job["job_id"])
        with self.assertRaises(ValueError):
            self.store.complete(job["job_id"], job["input_hash"], {"secret": secret})
        self.assertEqual(self.store.get(job["job_id"])["status"], "running")

    def test_invalid_identifiers_timeouts_and_non_json_results(self):
        for invalid in ("../job", "A" * 32, "a" * 32 + "\n", None):
            with self.subTest(job_id=invalid), self.assertRaises(ValueError):
                self.store.get(invalid)
        with self.assertRaises(KeyError):
            self.store.get("a" * 32)
        self.assertFalse(self.store.claim("a" * 32))
        job = self.store.submit(self.payload)
        for timeout in (0, -1, 3601, 1.5, True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.store.claim(job["job_id"], timeout)
        for result in ([], {"value": float("nan")}, {"value": object()}, {"value": "x" * 200_001}):
            with self.subTest(result_type=type(result).__name__), self.assertRaises(ValueError):
                self.store.complete(job["job_id"], job["input_hash"], result)


if __name__ == "__main__":
    unittest.main()
