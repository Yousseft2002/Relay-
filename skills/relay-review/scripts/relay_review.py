#!/usr/bin/env python3
"""Helper for the relay-review skill. Standard library only, Python 3.11+.

    relay_review.py roles  [--roles FILE] [--author AGENT] [--date YYYY-MM-DD]
    relay_review.py bundle [--base REF] [--out FILE] [--exclude GLOB ...] [--max-bytes N]
    relay_review.py check-report REPORT.md [--repo DIR]

This script never opens a network connection, never runs another agent, and only
runs read-only git commands. It writes files only under the output path you give it
(default .relay-review/, which it git-ignores with its own .gitignore).
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION = "0.1.0"

# ---- roles ----------------------------------------------------------------------------

CAPABILITIES = ("lead", "implement", "review", "security-review")
DEFAULT_ROLES_FILE = "relay-review.toml"


class RolesError(ValueError):
    pass


def load_roles(path: Path) -> dict:
    if not path.exists():
        raise RolesError(f"roles file not found: {path} (copy assets/roles.example.toml)")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    agents = raw.get("agents") or {}
    if not agents:
        raise RolesError("define at least one [agents.<id>] section")
    for name, a in agents.items():
        if not a.get("vendor"):
            raise RolesError(f"agents.{name}.vendor is required (the company behind the agent)")
        unknown = [c for c in a.get("capabilities", []) if c not in CAPABILITIES]
        if unknown:
            raise RolesError(f"agents.{name}.capabilities has unknown {unknown}; use {CAPABILITIES}")
        since = a.get("available_from")
        if since is not None and not isinstance(since, dt.date):
            raise RolesError(f"agents.{name}.available_from must be a TOML date like 2026-10-31")
    assign = raw.get("assign") or {}
    for role, value in assign.items():
        for agent in [value] if isinstance(value, str) else list(value):
            if agent not in agents:
                raise RolesError(f"assign.{role} names {agent!r}, which isn't in [agents]")
    return {"agents": agents, "assign": assign}


def availability(agent: dict, today: dt.date) -> tuple[bool, str]:
    if agent.get("available") is False:
        return False, agent.get("note") or "marked unavailable"
    since = agent.get("available_from")
    if since is not None and today < since:
        return False, f"unavailable until {since.isoformat()}"
    return True, "available"


def _ordered(roles: dict, role: str) -> list[str]:
    """Agents for a role: the assign list first, then every other agent in file order."""
    value = roles["assign"].get(role, [])
    preferred = [value] if isinstance(value, str) else list(value)
    return preferred + [a for a in roles["agents"] if a not in preferred]


def holder(roles: dict, role: str, today: dt.date) -> tuple[str | None, list[dict]]:
    """First available agent with the capability for `role`. Nothing is hardcoded."""
    skipped = []
    for name in _ordered(roles, role):
        agent = roles["agents"][name]
        if role not in agent.get("capabilities", []):
            continue
        ok, why = availability(agent, today)
        if ok:
            return name, skipped
        skipped.append({"agent": name, "reason": why})
    return None, skipped


def choose_reviewer(roles: dict, author: str, today: dt.date) -> dict:
    """An independent reviewer is a different agent from a different vendor."""
    agents = roles["agents"]
    if author not in agents:
        raise RolesError(f"author {author!r} isn't in [agents]; add it so its vendor is known")
    author_vendor = agents[author]["vendor"]
    skipped = []
    for name in _ordered(roles, "review"):
        agent = agents[name]
        if "review" not in agent.get("capabilities", []):
            continue
        if name == author:
            skipped.append({"agent": name, "reason": "is the author (that would be a self-review)"})
            continue
        if agent["vendor"] == author_vendor:
            skipped.append({"agent": name, "reason": f"same vendor as the author ({author_vendor})"})
            continue
        ok, why = availability(agent, today)
        if not ok:
            skipped.append({"agent": name, "reason": why})
            continue
        notes = []
        fam_a, fam_r = agents[author].get("model_family"), agent.get("model_family")
        if fam_a and fam_r and fam_a == fam_r:
            notes.append(f"both agents use the {fam_a} model family: independent agents, "
                         "not independent models")
        return {"mode": "independent", "author": author, "author_vendor": author_vendor,
                "reviewer": name, "reviewer_vendor": agent["vendor"],
                "invoke": agent.get("invoke", "manual"),
                "requires_authorization": True, "notes": notes, "skipped": skipped}
    return {"mode": "self-review", "author": author, "author_vendor": author_vendor,
            "reviewer": None, "reviewer_vendor": None, "invoke": None,
            "requires_authorization": False,
            "notes": ["no independent reviewer is available: the report must say "
                      "'not independent'"], "skipped": skipped}


def cmd_roles(args) -> int:
    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    try:
        roles = load_roles(Path(args.roles))
    except RolesError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2
    out: dict = {"date": today.isoformat(), "roles": {}}
    for role in ("lead", "implement"):
        name, skipped = holder(roles, role, today)
        out["roles"][role] = {"agent": name, "skipped": skipped}
    out["agents"] = {n: {"vendor": a["vendor"], "capabilities": a.get("capabilities", []),
                         "status": availability(a, today)[1]}
                     for n, a in roles["agents"].items()}
    if args.author:
        try:
            out["review"] = choose_reviewer(roles, args.author, today)
        except RolesError as exc:
            print(json.dumps({"error": str(exc)}, indent=2))
            return 2
    print(json.dumps(out, indent=2))
    return 0


# ---- secrets and sensitive files ------------------------------------------------------

SENSITIVE_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", ".npmrc", ".pypirc", ".netrc",
    ".git-credentials", "credentials", "credentials.*", "*secret*", "*.tfstate",
    "*.tfstate.*", "service-account*.json", ".aws/*", ".ssh/*", ".docker/config.json",
]
SAFE_GLOBS = [".env.example", ".env.sample", ".env.template"]

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("api-key-sk", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("url-credentials", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]{3,}(?=@)")),
    ("assigned-secret", re.compile(
        r"(?i)\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
        r"private[_-]?key|client[_-]?secret)[\w.-]*['\"]?\s*(?:[:=]|=>)\s*"
        r"(?P<q>['\"])(?!\[REDACTED)(?P<value>[^'\"\s]{8,})(?P=q)")),
]


def is_sensitive(path: str, extra: list[str] = ()) -> bool:
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, g) for g in SAFE_GLOBS):
        return False
    for glob in [*SENSITIVE_GLOBS, *extra]:
        if fnmatch.fnmatch(name.lower(), glob) or fnmatch.fnmatch(p.lower(), glob) \
                or fnmatch.fnmatch(p.lower(), f"*/{glob}"):
            return True
    return False


def redact(text: str) -> tuple[str, list[str]]:
    """Replace secret-looking values. Returns (text, kinds found). Values are never kept."""
    kinds: list[str] = []

    def sub(kind: str, pattern: re.Pattern, s: str) -> str:
        def repl(m: re.Match) -> str:
            kinds.append(kind)
            if kind == "assigned-secret":
                start, end = m.span("value")
                return m.group(0)[:start - m.start()] + f"[REDACTED:{kind}]" \
                    + m.group(0)[end - m.start():]
            return f"[REDACTED:{kind}]"
        return pattern.sub(repl, s)

    for kind, pattern in SECRET_PATTERNS:
        text = sub(kind, pattern, text)
    return text, kinds


INDEX_LINE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+(?P<mode> [0-7]+)?$", re.MULTILINE)


def scrub(section: str) -> tuple[str, list[str]]:
    """redact() for one file's diff. When a value was redacted, also hide the file's git blob
    ids: they hash the full content, secret included, so they'd let a weak secret be guessed."""
    clean, kinds = redact(section)
    if kinds:
        clean = INDEX_LINE.sub(lambda m: "index [REDACTED:blob-ids]" + (m["mode"] or ""),
                               clean, count=1)
    return clean, kinds


def find_secrets(text: str) -> list[str]:
    return [kind for kind, pattern in SECRET_PATTERNS if pattern.search(text)]


# ---- bundle ---------------------------------------------------------------------------

READ_ONLY_GIT = {"diff", "merge-base", "ls-files", "rev-parse", "symbolic-ref"}


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: Path, ok_codes: tuple[int, ...] = (0,)) -> str:
    if not args or args[0] not in READ_ONLY_GIT:
        raise GitError(f"refusing non-read-only git command: {args[:1]}")
    proc = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode not in ok_codes:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def default_base(cwd: Path) -> str:
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        try:
            git(["rev-parse", "--verify", "--quiet", ref], cwd)
            return ref
        except GitError:
            continue
    raise GitError("couldn't find a base branch; pass --base <ref>")


FILE_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$", re.MULTILINE)


def split_diff(diff: str) -> list[tuple[str, str]]:
    """[(path, section)] per file in a unified git diff."""
    starts = list(FILE_HEADER.finditer(diff))
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(diff)
        out.append((m.group("b"), diff[m.start():end]))
    return out


def is_python_artifact(path: str) -> bool:
    """Bytecode that running a project's tests leaves behind; not part of the change."""
    p = path.replace("\\", "/")
    return "__pycache__" in p.split("/") or p.endswith((".pyc", ".pyo"))


def diff_sections(cwd: Path, merge_base: str) -> list[tuple[str, str]]:
    """Every change from merge_base to the working tree, plus untracked files (except
    untracked Python bytecode)."""
    sections = split_diff(git(["diff", "--no-color", "--no-ext-diff", merge_base], cwd))
    untracked = [p for p in git(["ls-files", "--others", "--exclude-standard"], cwd).splitlines()
                 if p and not p.startswith(".relay-review/") and not is_python_artifact(p)]
    for path in untracked:
        text = git(["diff", "--no-color", "--no-index", "--", "/dev/null", path], cwd,
                   ok_codes=(0, 1))
        sections += split_diff(text) or [(path, "")]
    return sections


def fingerprint(sections: list[tuple[str, str]]) -> str:
    """A hash of exactly what a reviewer is shown: redacted diffs, and only the paths of
    sensitive files. It changes when the reviewed content changes (new commits, uncommitted
    edits, new files) and ignores --exclude and --max-bytes. Secret values never feed it, so
    the hash can't be used to guess them."""
    h = hashlib.sha256()
    for path, section in sorted(sections):
        h.update(path.encode("utf-8") + b"\0")
        h.update(b"[excluded]" if is_sensitive(path) else scrub(section)[0].encode("utf-8"))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def build_bundle(cwd: Path, base: str | None, extra_excludes: list[str],
                 max_bytes: int) -> tuple[str, dict]:
    cwd = Path(git(["rev-parse", "--show-toplevel"], cwd).strip())
    base = base or default_base(cwd)
    if base.startswith("-"):
        raise GitError(f"--base must be a git ref, not an option: {base!r}")
    merge_base = git(["merge-base", "HEAD", base], cwd).strip()
    head = git(["rev-parse", "HEAD"], cwd).strip()
    sections = diff_sections(cwd, merge_base)

    manifest = {"tool": f"relay-review {VERSION}", "base": base, "merge_base": merge_base,
                "head": head, "diff_sha256": fingerprint(sections),
                "includes_uncommitted": True, "files": [], "excluded": [],
                "redactions": [], "truncated": False}
    parts: list[str] = []
    for path, section in sections:
        if is_sensitive(path, extra_excludes):
            manifest["excluded"].append(path)
            continue
        clean, kinds = scrub(section)
        if kinds:
            manifest["redactions"].append({"file": path, "kinds": sorted(set(kinds)),
                                           "count": len(kinds)})
        manifest["files"].append(path)
        parts.append(clean)

    body = "".join(parts)
    if len(body.encode("utf-8")) > max_bytes:
        body = body.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
        body += "\n[... relay-review: diff truncated at --max-bytes; review the rest directly ...]\n"
        manifest["truncated"] = True

    header = ["# relay-review bundle",
              f"# base: {base} ({merge_base[:12]})  head: {head[:12]} + uncommitted changes",
              f"# record in the report: Base SHA {merge_base} | Head SHA {head} | "
              f"Diff fingerprint {manifest['diff_sha256']}",
              f"# files: {len(manifest['files'])}  excluded as sensitive (not shown): "
              f"{', '.join(manifest['excluded']) or 'none'}",
              f"# redacted values: {sum(r['count'] for r in manifest['redactions'])} "
              "(shown as [REDACTED:<kind>]; report the location, never the value)", ""]
    return "\n".join(header) + "\n" + body, manifest


def cmd_bundle(args) -> int:
    try:
        text, manifest = build_bundle(Path.cwd(), args.base, args.exclude or [], args.max_bytes)
    except GitError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.parent.name == ".relay-review":
        ignore = out.parent / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# created by relay-review; nothing here is meant to be committed\n*\n",
                              encoding="utf-8")
    out.write_text(text, encoding="utf-8")
    manifest["bundle"] = str(out)
    print(json.dumps(manifest, indent=2))
    return 0


# ---- report validation ----------------------------------------------------------------

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
BASES = ("confirmed", "traced", "suspected")
VERDICTS = ("approve", "request changes", "block")
REQUIRED_FIELDS = ("verdict", "independence", "author agent", "reviewer agent", "scope",
                   "base sha", "head sha", "diff fingerprint", "sharing authorization", "date")
REQUIRED_SECTIONS = ("summary", "findings", "coverage", "limitations")
FINDING = re.compile(r"^### (?P<id>F\d+) \[(?P<sev>[A-Z]+)\] (?P<title>.+)$", re.MULTILINE)
FIELD_ROW = re.compile(r"^\|\s*(?P<k>[^|]+?)\s*\|\s*(?P<v>[^|]*?)\s*\|\s*$", re.MULTILINE)
AGENT = re.compile(r"^(?P<name>[\w.-]+)\s*\((?P<vendor>[^)]+)\)")
LOCATION = re.compile(r"[\w./\\-]+:\d+")
NONE_VALUES = ("", "none", "n/a", "-", "not needed")
FULL_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")  # SHA-1 or SHA-256 repositories
DIFF_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
NOT_COMPUTED = "not computed"


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return {parts[i].strip().lower(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _bullet(block: str, key: str) -> str | None:
    m = re.search(rf"^- {key}:[ \t]*(?P<v>.*)$", block, re.MULTILINE | re.IGNORECASE)
    return m.group("v").strip() if m else None


def _plain(value: str) -> str:
    return value.strip().strip("`").strip().lower()


def check_freshness(fields: dict[str, str], repo: Path) -> list[str]:
    """Is the report about the code in `repo` right now? A review covers one exact state:
    once HEAD moves or the working tree changes, its verdict no longer applies."""
    base, head = _plain(fields["base sha"]), _plain(fields["head sha"])
    recorded = _plain(fields["diff fingerprint"])
    try:
        repo = Path(git(["rev-parse", "--show-toplevel"], repo).strip())
        current = git(["rev-parse", "HEAD"], repo).strip().lower()
        if current != head:
            return [f"stale: the report reviewed head {head[:12]} but the repository is at "
                    f"{current[:12]}; review the new commits"]
        if git(["merge-base", base, current], repo).strip().lower() != base:
            return [f"stale: base {base[:12]} is not an ancestor of head {current[:12]}"]
        if recorded == NOT_COMPUTED:
            return ["can't confirm freshness: 'diff fingerprint' is 'not computed'; rebuild the "
                    "bundle and record its diff_sha256"]
        if fingerprint(diff_sections(repo, base)) != recorded:
            return ["stale: the reviewed diff has changed since the review (uncommitted edits or "
                    "new files; see git status); review the current state"]
    except GitError as exc:
        return [f"can't confirm freshness: {exc}"]
    return []


def check_report(text: str, repo: Path | None = None) -> list[str]:
    """Problems with a report. With `repo`, also reject it if it's stale for that repo."""
    errors: list[str] = []
    fields = {m.group("k").strip().lower(): m.group("v").strip()
              for m in FIELD_ROW.finditer(text.split("\n## ", 1)[0])}
    for key in REQUIRED_FIELDS:
        if key not in fields:
            errors.append(f"header table is missing '{key}'")
    binding_ok = all(k in fields for k in ("base sha", "head sha", "diff fingerprint"))
    for key in ("base sha", "head sha"):
        if key in fields and not FULL_SHA.match(_plain(fields[key])):
            errors.append(f"'{key}' must be a full 40- or 64-character commit SHA, "
                          f"got {fields[key]!r}")
            binding_ok = False
    if "diff fingerprint" in fields:
        value = _plain(fields["diff fingerprint"])
        if not (DIFF_HASH.match(value) or value == NOT_COMPUTED):
            errors.append("'diff fingerprint' must be 'sha256:<64 hex>' from the bundle "
                          f"manifest, or '{NOT_COMPUTED}'")
            binding_ok = False
    sections = _sections(text)
    for name in REQUIRED_SECTIONS:
        if name not in sections:
            errors.append(f"missing section '## {name.title()}'")

    verdict = fields.get("verdict", "").lower()
    if verdict and verdict not in VERDICTS:
        errors.append(f"verdict must be one of {VERDICTS}, got {verdict!r}")

    independence = fields.get("independence", "").lower()
    claims_independent = independence.startswith("independent")
    if independence and not (claims_independent or independence.startswith("not independent")):
        errors.append("independence must start with 'independent' or 'not independent'")
    author, reviewer = (AGENT.match(fields.get(k, "")) for k in ("author agent", "reviewer agent"))
    for key, m in (("author agent", author), ("reviewer agent", reviewer)):
        if key in fields and not m:
            errors.append(f"'{key}' must look like 'agent-id (vendor)'")
    if claims_independent and author and reviewer:
        if author["name"].lower() == reviewer["name"].lower():
            errors.append("claims independence but the reviewer is the author (self-review)")
        elif author["vendor"].strip().lower() == reviewer["vendor"].strip().lower():
            errors.append("claims independence but reviewer and author share a vendor")
        if fields.get("sharing authorization", "").lower() in NONE_VALUES:
            errors.append("independent review by another vendor needs a recorded "
                          "'sharing authorization'")

    body = sections.get("findings", "")
    findings = list(FINDING.finditer(body))
    severities = []
    for i, m in enumerate(findings):
        end = findings[i + 1].start() if i + 1 < len(findings) else len(body)
        block = body[m.end():end]
        fid, sev = m.group("id"), m.group("sev")
        if sev not in SEVERITIES:
            errors.append(f"{fid}: severity must be one of {SEVERITIES}")
            continue
        severities.append(sev)
        location, basis = _bullet(block, "Location"), (_bullet(block, "Basis") or "").lower()
        evidence = _bullet(block, "Evidence")
        if basis.split(" ")[0] not in BASES:
            errors.append(f"{fid}: 'Basis' must be one of {BASES}")
        if evidence is None or (not evidence and "```" not in block):
            errors.append(f"{fid}: needs '- Evidence:' with a quote, command output or trace")
        if sev in ("CRITICAL", "HIGH") and basis.startswith("suspected"):
            errors.append(f"{fid}: {sev} needs basis 'confirmed' or 'traced', not 'suspected'")
        if sev in ("CRITICAL", "HIGH", "MEDIUM") and not (location and LOCATION.search(location)):
            errors.append(f"{fid}: {sev} needs '- Location: path:line'")
        if not _bullet(block, "Fix") and sev != "INFO":
            errors.append(f"{fid}: needs '- Fix:'")

    if "CRITICAL" in severities and verdict != "block":
        errors.append("a CRITICAL finding requires verdict 'block'")
    elif "HIGH" in severities and verdict == "approve":
        errors.append("a HIGH finding can't be approved; use 'request changes' or 'block'")

    rr = re.search(r"RELAY_RESULT\s*(\{.*?\})\s*END_RELAY_RESULT", text, re.DOTALL)
    if not rr:
        errors.append("missing the RELAY_RESULT block")
    else:
        try:
            data = json.loads(rr.group(1))
            want = "approve" if verdict == "approve" else "request_changes"
            if data.get("verdict") != want:
                errors.append(f"RELAY_RESULT verdict should be {want!r} for verdict {verdict!r}")
            blocking = sum(s in ("CRITICAL", "HIGH") for s in severities)
            if len(data.get("blocking_issues") or []) != blocking:
                errors.append(f"RELAY_RESULT should list {blocking} blocking issue(s) "
                              "(the CRITICAL and HIGH findings)")
        except json.JSONDecodeError as exc:
            errors.append(f"RELAY_RESULT isn't valid JSON: {exc}")

    leaked = find_secrets(text)
    if leaked:
        errors.append(f"report contains secret-like values ({', '.join(sorted(set(leaked)))}); "
                      "describe the location instead of quoting the value")
    if repo is not None and binding_ok:
        errors += check_freshness(fields, repo)
    return errors


def cmd_check_report(args) -> int:
    path = Path(args.report)
    if not path.exists():
        print(f"not found: {path}")
        return 2
    errors = check_report(path.read_text(encoding="utf-8"),
                          Path(args.repo) if args.repo else None)
    if errors:
        print(f"{path}: {len(errors)} problem(s)")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"{path}: OK")
    return 0


# ---- cli ------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="relay_review.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("roles", help="show who holds each role and pick an independent reviewer")
    r.add_argument("--roles", default=DEFAULT_ROLES_FILE)
    r.add_argument("--author", help="agent id that wrote the change")
    r.add_argument("--date", help="evaluate availability on this date (default: today)")
    r.set_defaults(func=cmd_roles)

    b = sub.add_parser("bundle", help="diff vs base, without sensitive files and secret values")
    b.add_argument("--base", help="base ref (default: origin/HEAD, else main/master)")
    b.add_argument("--out", default=".relay-review/bundle.diff")
    b.add_argument("--exclude", action="append", help="extra glob to treat as sensitive")
    b.add_argument("--max-bytes", type=int, default=300_000)
    b.set_defaults(func=cmd_bundle)

    c = sub.add_parser("check-report", help="validate a review report against the rubric")
    c.add_argument("report")
    c.add_argument("--repo", help="also reject the report if it's stale: its Head SHA and diff "
                                  "fingerprint must match this repository's current state")
    c.set_defaults(func=cmd_check_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
