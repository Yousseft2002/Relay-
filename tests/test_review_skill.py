"""The relay-review skill: package rules, roles, safe bundles, report checks, fixtures."""
import ast
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from relay.result import parse_review

from .relay_review_eval import (CASES, FIXTURES, SCRIPT, SEVERITY_RANK, SKILL_DIR, build_repo,
                                case_names, grade, load_case, load_script)

rr = load_script()
ROLES_EXAMPLE = SKILL_DIR / "assets" / "roles.example.toml"
REPORTS = FIXTURES / "reports"
BEFORE, AFTER = dt.date(2026, 10, 28), dt.date(2026, 11, 1)


def frontmatter(text: str) -> dict:
    """Enough YAML for SKILL.md: top-level scalars plus one level of nested scalars."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md must start with a --- frontmatter block"
    data: dict = {}
    parent = None
    for line in m.group(1).splitlines():
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if line.startswith("  ") and parent is not None:
            data[parent][key] = value
        elif value:
            data[key], parent = value, None
        else:
            data[key], parent = {}, key
    return data


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        self.skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    def test_frontmatter_follows_agent_skills_spec(self):
        fm = frontmatter(self.skill_md)
        self.assertLessEqual(set(fm), {"name", "description", "license", "compatibility",
                                       "metadata", "allowed-tools"})
        self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fm["name"]), 64)
        self.assertEqual(fm["name"], SKILL_DIR.name)
        self.assertTrue(0 < len(fm["description"]) <= 1024, len(fm["description"]))
        self.assertLessEqual(len(fm["compatibility"]), 500)
        for value in fm["metadata"].values():
            self.assertRegex(value, r'^".*"$', "metadata values must be strings")
        self.assertTrue((SKILL_DIR / "LICENSE").exists())

    def test_skill_md_is_short_enough_to_load(self):
        self.assertLess(len(self.skill_md.splitlines()), 500)

    def test_relative_links_resolve(self):
        for md in SKILL_DIR.rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", md.read_text(encoding="utf-8")):
                if target.startswith(("http", "#", "mailto:")):
                    continue
                path = (md.parent / target.split("#")[0]).resolve()
                self.assertTrue(path.exists(), f"{md.name} links to missing {target}")

    def test_package_holds_only_reviewable_text_files(self):
        for path in SKILL_DIR.rglob("*"):
            if path.is_file():
                self.assertTrue(path.suffix in (".md", ".py", ".toml") or path.name == "LICENSE",
                                f"unexpected file in package: {path}")

    def test_package_has_no_secrets_or_planted_instructions(self):
        for path in SKILL_DIR.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertEqual(rr.find_secrets(text), [], path)
            self.assertNotRegex(text.lower(), r"ignore (all |your )?previous instructions", path)

    def test_script_imports_nothing_that_can_reach_the_network(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        allowed = {"__future__", "argparse", "datetime", "fnmatch", "hashlib", "json", "re",
                   "subprocess", "sys", "tomllib", "pathlib"}
        self.assertLessEqual(imported, allowed)

    def test_only_the_git_helper_starts_processes(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(func):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == "subprocess"):
                    self.assertEqual(func.name, "git", f"subprocess used in {func.name}()")

    def test_git_helper_refuses_commands_that_change_anything(self):
        for command in (["push"], ["commit", "-m", "x"], ["checkout", "main"], ["fetch"], []):
            with self.assertRaises(rr.GitError):
                rr.git(command, Path.cwd())


class RolesTests(TempDirCase):
    def roles(self, text: str | None = None) -> dict:
        if text is None:
            return rr.load_roles(ROLES_EXAMPLE)
        path = self.tmp / "relay-review.toml"
        path.write_text(text, encoding="utf-8")
        return rr.load_roles(path)

    def test_copilot_reviews_claude_code_while_codex_is_unavailable(self):
        pick = rr.choose_reviewer(self.roles(), "claude-code", BEFORE)
        self.assertEqual((pick["mode"], pick["reviewer"]), ("independent", "copilot"))
        self.assertTrue(pick["requires_authorization"])
        self.assertEqual(pick["invoke"], "manual")

    def test_codex_returns_on_its_date(self):
        text = ROLES_EXAMPLE.read_text(encoding="utf-8").replace(
            'invoke = "manual"', 'available = false\ninvoke = "manual"')
        roles = self.roles(text)
        before = rr.choose_reviewer(roles, "claude-code", BEFORE)
        self.assertEqual(before["mode"], "self-review")
        self.assertIn({"agent": "codex", "reason": "unavailable until 2026-10-31"},
                      before["skipped"])
        self.assertIn("claude-code", [s["agent"] for s in before["skipped"]])
        self.assertEqual(rr.choose_reviewer(roles, "claude-code", AFTER)["reviewer"], "codex")

    def test_lead_is_configuration_not_hardcoded(self):
        self.assertEqual(rr.holder(self.roles(), "lead", BEFORE)[0], "claude-code")
        text = ROLES_EXAMPLE.read_text(encoding="utf-8").replace(
            'lead = ["claude-code", "codex"]', 'lead = ["codex", "claude-code"]')
        roles = self.roles(text)
        self.assertEqual(rr.holder(roles, "lead", BEFORE)[0], "claude-code")  # codex not back yet
        self.assertEqual(rr.holder(roles, "lead", AFTER)[0], "codex")

    def test_other_authors_get_reviewers_too(self):
        roles = self.roles()
        self.assertEqual(rr.choose_reviewer(roles, "copilot", BEFORE)["reviewer"], "claude-code")
        self.assertEqual(rr.choose_reviewer(roles, "copilot", AFTER)["reviewer"], "codex")

    def test_same_vendor_is_never_independent(self):
        roles = self.roles(
            '[agents.claude-code]\nvendor = "anthropic"\ncapabilities = ["implement", "review"]\n'
            '[agents.claude-subagent]\nvendor = "anthropic"\ncapabilities = ["review"]\n')
        pick = rr.choose_reviewer(roles, "claude-code", BEFORE)
        self.assertEqual(pick["mode"], "self-review")
        self.assertIsNone(pick["reviewer"])
        self.assertIn("same vendor", pick["skipped"][-1]["reason"])

    def test_same_model_family_is_flagged(self):
        text = ROLES_EXAMPLE.read_text(encoding="utf-8").replace(
            'model_family = "varies"', 'model_family = "claude"')
        pick = rr.choose_reviewer(self.roles(text), "claude-code", BEFORE)
        self.assertEqual(pick["reviewer"], "copilot")
        self.assertIn("model family", pick["notes"][0])

    def test_bad_roles_files_are_rejected(self):
        with self.assertRaisesRegex(rr.RolesError, "vendor"):
            self.roles('[agents.a]\ncapabilities = ["review"]\n')
        with self.assertRaisesRegex(rr.RolesError, "capabilities"):
            self.roles('[agents.a]\nvendor = "x"\ncapabilities = ["deploy"]\n')
        with self.assertRaisesRegex(rr.RolesError, "isn't in"):
            self.roles('[agents.a]\nvendor = "x"\n[assign]\nreview = ["ghost"]\n')
        with self.assertRaisesRegex(rr.RolesError, "author"):
            rr.choose_reviewer(self.roles(), "ghost", BEFORE)

    def test_cli_prints_assignment(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "roles", "--roles", str(ROLES_EXAMPLE),
                              "--author", "claude-code", "--date", "2026-10-28"],
                             capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        self.assertEqual(data["review"]["reviewer"], "copilot")
        self.assertEqual(data["roles"]["lead"]["agent"], "claude-code")
        self.assertEqual(data["agents"]["codex"]["status"], "unavailable until 2026-10-31")


class RedactionTests(unittest.TestCase):
    # Token-shaped strings are assembled at run time so none sits in the repo verbatim.
    def test_known_token_shapes_are_redacted(self):
        samples = {
            "github-token": "gh" + "p_" + "A1" * 18,
            "aws-access-key": "AKIA" + "B" * 16,
            "private-key": "-----BEGIN " + "RSA PRIVATE KEY-----",
            "api-key-sk": "sk-" + "x" * 24,
            "url-credentials": "postgres://admin:" + "hunter22" + "@db.internal/app",
            "assigned-secret": '"api_key": "' + "abc123def456" + '"',
        }
        for kind, sample in samples.items():
            clean, kinds = rr.redact(f"value = {sample}\n")
            self.assertIn(kind, kinds, sample)
            self.assertIn(f"[REDACTED:{kind}]", clean)

    def test_ordinary_code_is_left_alone(self):
        for line in ('token = get_token()', 'password = ""', 'PASSWORD_MIN_LENGTH = 12',
                     'key = "[REDACTED:assigned-secret]"', 'url = "https://example.com/a:b"'):
            self.assertEqual(rr.redact(line), (line, []), line)

    def test_sensitive_paths(self):
        for path in (".env", "config/.env.production", "deploy/id_rsa", "keys/server.pem",
                     "src/secrets.py", "infra/terraform.tfstate", ".aws/credentials"):
            self.assertTrue(rr.is_sensitive(path), path)
        for path in (".env.example", "README.md", "app/settings.py", "docs/environment.md"):
            self.assertFalse(rr.is_sensitive(path), path)
        self.assertTrue(rr.is_sensitive("data/customers.csv", ["*.csv"]))


class BundleTests(TempDirCase):
    def test_every_case_bundles_safely(self):
        for name in case_names():
            with self.subTest(case=name):
                case = load_case(name)
                repo = build_repo(name, self.tmp / name)
                text, manifest = rr.build_bundle(repo, "main", [], 300_000)
                want = case["bundle"]
                self.assertEqual(sorted(manifest["excluded"]), sorted(want["excluded"]))
                self.assertLessEqual(set(want.get("included", [])), set(manifest["files"]))
                self.assertEqual(sorted(r["file"] for r in manifest["redactions"]),
                                 sorted(want["redacted"]))
                for item in case["must_find"]:
                    if "contains" in item and item["file"] not in manifest["excluded"]:
                        self.assertIn(item["contains"], text)
                self.assertNotIn("fake_live_key_for_fixture", text)
                self.assertNotIn("fixture-not-a-real-password", text)
                self.assertEqual(rr.find_secrets(text), [])

    def test_redacted_files_do_not_expose_blob_ids(self):
        # A blob id hashes the whole file, secret included, so it could be used to guess it.
        repo = build_repo("hardcoded-secret", self.tmp / "repo")
        text, _ = rr.build_bundle(repo, "main", [], 300_000)
        section = text[text.index("diff --git a/billing/client.py"):]
        self.assertIn("index [REDACTED:blob-ids]", section)
        self.assertNotRegex(section, r"(?m)^index [0-9a-f]+\.\.[0-9a-f]+")
        clean_repo = build_repo("sql-injection", self.tmp / "clean")
        self.assertRegex(rr.build_bundle(clean_repo, "main", [], 300_000)[0],
                         r"(?m)^index [0-9a-f]+\.\.[0-9a-f]+")  # unredacted files keep theirs

    def test_uncommitted_and_untracked_changes_are_included(self):
        repo = build_repo("sql-injection", self.tmp / "repo", commit_head=False)
        text, manifest = rr.build_bundle(repo, "main", [], 300_000)
        self.assertEqual(sorted(manifest["files"]), ["app/users.py", "app/web.py"])
        self.assertIn("handle_search", text)  # app/web.py is untracked

    def test_base_cannot_smuggle_git_options(self):
        repo = build_repo("sql-injection", self.tmp / "repo")
        with self.assertRaisesRegex(rr.GitError, "not an option"):
            rr.build_bundle(repo, "--output=pwned.txt", [], 300_000)
        self.assertFalse((repo / "pwned.txt").exists())

    def test_truncation_is_reported(self):
        repo = build_repo("sql-injection", self.tmp / "repo")
        text, manifest = rr.build_bundle(repo, "main", [], 200)
        self.assertTrue(manifest["truncated"])
        self.assertIn("diff truncated", text)

    def test_cli_writes_only_into_a_self_ignoring_folder(self):
        repo = build_repo("hardcoded-secret", self.tmp / "repo")
        out = subprocess.run([sys.executable, str(SCRIPT), "bundle", "--base", "main"],
                             cwd=repo, capture_output=True, text=True, check=True)
        manifest = json.loads(out.stdout)
        self.assertEqual(manifest["redactions"][0]["file"], "billing/client.py")
        self.assertTrue((repo / ".relay-review" / "bundle.diff").exists())
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(status, "")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.independent = (REPORTS / "sql-injection.independent.md").read_text(encoding="utf-8")
        self.self_review = (REPORTS / "clean-change.self-review.md").read_text(encoding="utf-8")

    def errors_after(self, old: str, new: str, report: str | None = None) -> list[str]:
        report = report or self.independent
        self.assertIn(old, report)
        return rr.check_report(report.replace(old, new, 1))

    def assertRejected(self, errors: list[str], fragment: str):
        self.assertTrue(any(fragment in e for e in errors), f"{fragment!r} not in {errors}")

    def test_sample_reports_pass(self):
        self.assertEqual(rr.check_report(self.independent), [])
        self.assertEqual(rr.check_report(self.self_review), [])

    def test_sample_reports_grade_against_their_cases(self):
        self.assertEqual(grade(self.independent, load_case("sql-injection")), [])
        self.assertEqual(grade(self.self_review, load_case("clean-change")), [])

    def test_grader_notices_a_missed_issue(self):
        problems = grade(self.self_review, load_case("sql-injection"))
        self.assertTrue(any(p.startswith("missed") for p in problems), problems)

    def test_relay_parses_the_result_block(self):
        review = parse_review(self.independent)
        self.assertEqual(review["verdict"], "request_changes")
        self.assertEqual(len(review["blocking_issues"]), 1)
        self.assertTrue(parse_review(self.self_review)["parsed"])
        self.assertEqual(parse_review(self.self_review)["verdict"], "approve")

    def test_self_review_claiming_independence(self):
        self.assertRejected(self.errors_after("| Reviewer agent | copilot (github) |",
                                              "| Reviewer agent | claude-code (anthropic) |"),
                            "reviewer is the author")
        self.assertRejected(self.errors_after("not independent (self-review)", "independent",
                                              self.self_review), "reviewer is the author")

    def test_same_vendor_claiming_independence(self):
        self.assertRejected(self.errors_after("| Reviewer agent | copilot (github) |",
                                              "| Reviewer agent | claude-subagent (anthropic) |"),
                            "share a vendor")

    def test_independent_review_needs_recorded_authorization(self):
        self.assertRejected(self.errors_after(
            '| Sharing authorization | granted by repo owner on 2026-10-28: "yes, Copilot can '
            'review this branch" |', "| Sharing authorization | none |"), "sharing authorization")

    def test_high_needs_traced_or_confirmed_evidence(self):
        self.assertRejected(self.errors_after("- Basis: traced", "- Basis: suspected"),
                            "needs basis 'confirmed' or 'traced'")

    def test_finding_needs_location_and_evidence(self):
        self.assertRejected(self.errors_after("- Location: `app/users.py:10`", "- Location: somewhere"),
                            "needs '- Location: path:line'")
        start = self.independent.index("- Evidence:")
        end = self.independent.index("- Why it matters")
        errors = rr.check_report(self.independent[:start] + self.independent[end:])
        self.assertRejected(errors, "needs '- Evidence:'")

    def test_verdict_must_match_severities(self):
        errors = self.errors_after("| Verdict | request changes |", "| Verdict | approve |")
        self.assertRejected(errors, "can't be approved")
        self.assertRejected(errors, "RELAY_RESULT verdict")
        self.assertRejected(self.errors_after("### F1 [HIGH]", "### F1 [CRITICAL]"),
                            "requires verdict 'block'")

    def test_result_block_must_match_findings(self):
        self.assertRejected(self.errors_after('"blocking_issues": [{"file": "app/users.py", '
                                              '"line": "10", "issue": "SQL injection in '
                                              'search_users via the q parameter", "fix": "Use a '
                                              'bound parameter"}]', '"blocking_issues": []'),
                            "blocking issue")
        self.assertRejected(self.errors_after("END_RELAY_RESULT", ""), "missing the RELAY_RESULT")

    def test_leaked_secret_is_rejected(self):
        leaked = self.independent.replace(
            "## Coverage", 'Seen: PAYMENT_API_KEY = "fake_live_key_for_fixture_0123456789"\n\n'
            "## Coverage")
        self.assertRejected(rr.check_report(leaked), "secret-like")

    def test_template_and_checker_agree_on_structure(self):
        template = (SKILL_DIR / "assets" / "report-template.md").read_text(encoding="utf-8")
        rows = {m.group("k").strip().lower() for m in rr.FIELD_ROW.finditer(template)}
        self.assertLessEqual(set(rr.REQUIRED_FIELDS), rows)
        for section in rr.REQUIRED_SECTIONS:
            self.assertRegex(template, rf"(?mi)^## {section}\s*$")
        self.assertIn("RELAY_RESULT", template)

    def test_cli_exit_codes(self):
        ok = subprocess.run([sys.executable, str(SCRIPT), "check-report",
                             str(REPORTS / "sql-injection.independent.md")],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        bad = subprocess.run([sys.executable, str(SCRIPT), "check-report",
                              str(SKILL_DIR / "assets" / "report-template.md")],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)


class ReviewBindingTests(unittest.TestCase):
    """The header names the exact commits and diff that were reviewed."""

    def setUp(self):
        self.report = (REPORTS / "sql-injection.independent.md").read_text(encoding="utf-8")

    def without_row(self, field: str) -> str:
        return re.sub(rf"(?m)^\| {field} \|.*\n", "", self.report, count=1)

    def test_each_binding_row_is_required(self):
        for field in ("Base SHA", "Head SHA", "Diff fingerprint"):
            with self.subTest(field=field):
                text = self.without_row(field)
                self.assertNotEqual(text, self.report)
                self.assertIn(f"header table is missing '{field.lower()}'", rr.check_report(text))

    def test_cli_names_the_missing_head_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text(self.without_row("Head SHA"), encoding="utf-8")
            out = subprocess.run([sys.executable, str(SCRIPT), "check-report", str(path)],
                                 capture_output=True, text=True)
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("head sha", out.stdout)

    def set_row(self, field: str, value: str) -> list[str]:
        text, n = re.subn(rf"(?m)^\| {field} \|.*$", f"| {field} | {value} |", self.report)
        self.assertEqual(n, 1)
        return rr.check_report(text)

    def test_sha_must_be_full(self):
        for bad in ("abc1234", "a" * 39, "g" * 40, "a" * 41, "HEAD", "not reported"):
            with self.subTest(value=bad):
                self.assertTrue(any("'head sha' must be a full" in e
                                    for e in self.set_row("Head SHA", bad)))

    def test_sha_formats_that_are_accepted(self):
        for good in ("a" * 40, "A" * 40, "`" + "b" * 40 + "`", "c" * 64):
            with self.subTest(value=good):
                self.assertEqual(self.set_row("Base SHA", good), [])

    def test_fingerprint_format(self):
        self.assertEqual(self.set_row("Diff fingerprint", "not computed"), [])
        for bad in ("sha256:abc", "d" * 64, "md5:" + "d" * 32, ""):
            with self.subTest(value=bad):
                self.assertTrue(any("'diff fingerprint' must be" in e
                                    for e in self.set_row("Diff fingerprint", bad)))


def git_run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


class FreshnessTests(TempDirCase):
    """With --repo, a report only passes for the exact state it reviewed."""

    def setUp(self):
        super().setUp()
        self.repo = build_repo("sql-injection", self.tmp / "repo")
        self.sample = (REPORTS / "sql-injection.independent.md").read_text(encoding="utf-8")

    def report_for(self, repo: Path, **override) -> str:
        _, manifest = rr.build_bundle(repo, "main", [], 300_000)
        values = {"Base SHA": manifest["merge_base"], "Head SHA": manifest["head"],
                  "Diff fingerprint": manifest["diff_sha256"], **override}
        text = self.sample
        for field, value in values.items():
            text, n = re.subn(rf"(?m)^\| {field} \|.*$", f"| {field} | {value} |", text)
            self.assertEqual(n, 1)
        return text

    def assertStale(self, errors: list[str], fragment: str = "stale"):
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_report_for_the_current_state_is_fresh(self):
        self.assertEqual(rr.check_report(self.report_for(self.repo), self.repo), [])

    def test_bundle_surfaces_full_shas(self):
        text, manifest = rr.build_bundle(self.repo, "main", [], 300_000)
        self.assertRegex(manifest["head"], r"^[0-9a-f]{40}$")
        self.assertRegex(manifest["diff_sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn(f"Head SHA {manifest['head']}", text)
        self.assertIn(f"Diff fingerprint {manifest['diff_sha256']}", text)

    def test_new_commit_makes_the_review_stale(self):
        report = self.report_for(self.repo)
        (self.repo / "app" / "users.py").write_text("# rewritten\n", encoding="utf-8")
        git_run(self.repo, "commit", "-qam", "after review")
        self.assertStale(rr.check_report(report, self.repo), "stale: the report reviewed head")

    def test_uncommitted_edit_makes_the_review_stale(self):
        report = self.report_for(self.repo)
        with (self.repo / "app" / "users.py").open("a", encoding="utf-8") as fh:
            fh.write("# edited after review\n")
        self.assertStale(rr.check_report(report, self.repo), "reviewed diff has changed")

    def test_new_untracked_file_makes_the_review_stale(self):
        report = self.report_for(self.repo)
        (self.repo / "app" / "extra.py").write_text("x = 1\n", encoding="utf-8")
        self.assertStale(rr.check_report(report, self.repo), "reviewed diff has changed")

    def test_python_bytecode_and_the_review_folder_do_not_count(self):
        report = self.report_for(self.repo)
        (self.repo / "app" / "__pycache__").mkdir()
        (self.repo / "app" / "__pycache__" / "users.cpython-311.pyc").write_bytes(b"\0bytecode")
        (self.repo / ".relay-review" / "reports").mkdir(parents=True)
        (self.repo / ".relay-review" / "reports" / "r.md").write_text(report, encoding="utf-8")
        self.assertEqual(rr.check_report(report, self.repo), [])

    def test_unknown_base_is_rejected(self):
        report = self.report_for(self.repo, **{"Base SHA": "e" * 40})
        self.assertStale(rr.check_report(report, self.repo), "can't confirm freshness")

    def test_base_must_be_an_ancestor_of_head(self):
        git_run(self.repo, "switch", "-q", "main")
        (self.repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
        git_run(self.repo, "add", "other.txt")
        git_run(self.repo, "commit", "-qm", "main moves on")
        main_tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, check=True,
                                  capture_output=True, text=True).stdout.strip()
        git_run(self.repo, "switch", "-q", "feature")
        report = self.report_for(self.repo, **{"Base SHA": main_tip})
        self.assertStale(rr.check_report(report, self.repo), "is not an ancestor")

    def test_not_computed_cannot_be_confirmed_fresh(self):
        report = self.report_for(self.repo, **{"Diff fingerprint": "not computed"})
        self.assertEqual(rr.check_report(report), [])
        self.assertStale(rr.check_report(report, self.repo), "'not computed'")

    def test_fingerprint_ignores_bundle_options(self):
        prints = {rr.build_bundle(self.repo, "main", excl, size)[1]["diff_sha256"]
                  for excl, size in (([], 300_000), (["*.py"], 300_000), ([], 200))}
        self.assertEqual(len(prints), 1)

    def test_secret_values_never_feed_the_fingerprint(self):
        repo = build_repo("hardcoded-secret", self.tmp / "secret")
        before = rr.build_bundle(repo, "main", [], 300_000)[1]["diff_sha256"]
        client = repo / "billing" / "client.py"
        data = client.read_bytes()  # bytes, so line endings stay as they are
        self.assertIn(b"fake_live_key_for_fixture", data)
        client.write_bytes(data.replace(b"fake_live_key_for_fixture", b"fake_other_key_for_fixtur"))
        self.assertEqual(rr.build_bundle(repo, "main", [], 300_000)[1]["diff_sha256"], before)

    def test_cli_repo_flag_rejects_a_stale_report(self):
        path = self.repo / ".relay-review" / "reports" / "review.md"
        path.parent.mkdir(parents=True)
        path.write_text(self.report_for(self.repo), encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), "check-report", str(path), "--repo", str(self.repo)]
        fresh = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(fresh.returncode, 0, fresh.stdout)
        (self.repo / "app" / "users.py").write_text("# changed\n", encoding="utf-8")
        stale = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(stale.returncode, 1, stale.stdout)
        self.assertIn("stale", stale.stdout)


class FixtureTests(unittest.TestCase):
    def test_cases_are_complete_and_consistent(self):
        names = case_names()
        self.assertGreaterEqual(len(names), 7)
        for name in names:
            with self.subTest(case=name):
                case = load_case(name)  # raises if a 'contains' line isn't unique
                self.assertTrue((CASES / name / "base").is_dir())
                self.assertTrue((CASES / name / "head").is_dir())
                for item in case["must_find"]:
                    self.assertIn(item["min_severity"], SEVERITY_RANK)
                    self.assertTrue((CASES / name / "head" / item["file"]).exists())
                self.assertTrue(case["must_find"] or "max_severity" in case,
                                "a case must expect findings or cap them")


if __name__ == "__main__":
    unittest.main()
