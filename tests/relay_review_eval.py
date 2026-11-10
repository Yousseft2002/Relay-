"""Build relay-review fixture repos and grade review reports against them.

    py -m tests.relay_review_eval build <case> <dest-dir>   # a git repo to review
    py -m tests.relay_review_eval grade <case> <report.md>  # did the review find it?
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "relay-review"
SCRIPT = SKILL_DIR / "scripts" / "relay_review.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "relay-review"
CASES = FIXTURES / "cases"
SEVERITY_RANK = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def load_script():
    """Import the skill's script without leaving __pycache__ inside the skill package."""
    spec = importlib.util.spec_from_file_location("relay_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


def case_names() -> list[str]:
    return sorted(p.name for p in CASES.iterdir() if (p / "expected.json").exists())


def load_case(name: str) -> dict:
    """expected.json with each must_find 'contains' resolved to a head line number."""
    case = json.loads((CASES / name / "expected.json").read_text(encoding="utf-8"))
    for item in case["must_find"]:
        if "contains" in item:
            lines = (CASES / name / "head" / item["file"]).read_text(encoding="utf-8").splitlines()
            hits = [i for i, line in enumerate(lines, 1) if item["contains"] in line]
            if len(hits) != 1:
                raise ValueError(f"{name}: {item['contains']!r} found on lines {hits}, need one")
            item["line"] = hits[0]
    return case


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def build_repo(name: str, dest: Path, commit_head: bool = True) -> Path:
    """A repo with base on main and head on branch 'feature'."""
    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "user.email", "fixture@example.com")
    _git(dest, "config", "user.name", "Fixture")
    _git(dest, "config", "core.autocrlf", "false")
    shutil.copytree(CASES / name / "base", dest, dirs_exist_ok=True)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "base")
    _git(dest, "switch", "-q", "-c", "feature")
    shutil.copytree(CASES / name / "head", dest, dirs_exist_ok=True)
    if commit_head:
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "-m", "head")
    return dest


FINDING = re.compile(r"^### (?P<id>F\d+) \[(?P<sev>[A-Z]+)\] (?P<title>.+)$", re.MULTILINE)
LOCATION = re.compile(r"(?P<file>[\w./\\-]+):(?P<line>\d+)")


def parse_findings(report: str) -> list[dict]:
    body = re.split(r"^## Findings\s*$", report, flags=re.MULTILINE)
    body = re.split(r"^## ", body[1], flags=re.MULTILINE)[0] if len(body) > 1 else ""
    matches = list(FINDING.finditer(body))
    out = []
    for i, m in enumerate(matches):
        block = body[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(body)]
        loc_line = re.search(r"^- Location:(.*)$", block, re.MULTILINE)
        locations = [(l["file"].replace("\\", "/").removeprefix("./"), int(l["line"]))
                     for l in LOCATION.finditer(loc_line.group(1) if loc_line else "")]
        out.append({"id": m["id"], "severity": m["sev"], "title": m["title"],
                    "locations": locations, "text": (m["title"] + block).lower()})
    return out


def verdict_of(report: str) -> str:
    m = re.search(r"^\|\s*Verdict\s*\|\s*([^|]+?)\s*\|", report, re.MULTILINE | re.IGNORECASE)
    return m.group(1).lower() if m else ""


def grade(report: str, case: dict) -> list[str]:
    """Problems with a report for a case; empty means the review caught what it should."""
    problems = []
    findings = parse_findings(report)
    for item in case["must_find"]:
        tolerance = item.get("line_tolerance", 3)
        rank = SEVERITY_RANK[item["min_severity"]]

        def matches(f: dict) -> bool:
            at = any(file.endswith(item["file"]) and abs(line - item["line"]) <= tolerance
                     for file, line in f["locations"])
            keyed = not item.get("keywords") or any(k.lower() in f["text"] for k in item["keywords"])
            return at and keyed and SEVERITY_RANK.get(f["severity"], -1) >= rank

        if not any(matches(f) for f in findings):
            problems.append(f"missed: {item['min_severity']}+ at {item['file']}:{item['line']} "
                            f"({'/'.join(item.get('keywords', []))})")
    if "max_severity" in case:
        cap = SEVERITY_RANK[case["max_severity"]]
        for f in findings:
            if SEVERITY_RANK.get(f["severity"], 0) > cap:
                problems.append(f"false positive? {f['id']} [{f['severity']}] {f['title']}")
    verdict = verdict_of(report)
    if "verdict" in case and verdict != case["verdict"]:
        problems.append(f"verdict {verdict!r}, expected {case['verdict']!r}")
    if "verdict_not" in case and verdict == case["verdict_not"]:
        problems.append(f"verdict must not be {case['verdict_not']!r}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("build", "grade"):
        print(__doc__)
        return 2
    command, name, target = argv
    if command == "build":
        print(build_repo(name, Path(target)))
        return 0
    case = load_case(name)
    report = Path(target).read_text(encoding="utf-8")
    problems = grade(report, case)
    errors = load_script().check_report(report)
    for p in problems + [f"check-report: {e}" for e in errors]:
        print(f"- {p}")
    print("PASS" if not problems and not errors else "FAIL")
    return 0 if not problems and not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
