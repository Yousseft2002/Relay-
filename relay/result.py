"""Parse the structured block every agent ends its run with."""
from __future__ import annotations

import json
import re

START, END = "RELAY_RESULT", "END_RELAY_RESULT"
FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _last_json_object(text: str) -> dict | None:
    """Find the last balanced {...} that parses as JSON."""
    end = text.rfind("}")
    while end != -1:
        depth = 0
        for start in range(end, -1, -1):
            ch = text[start]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:end + 1])
                        if isinstance(value, dict):
                            return value
                    except json.JSONDecodeError:
                        pass
                    break
        end = text.rfind("}", 0, end)
    return None


def extract_json(text: str) -> dict | None:
    if not text:
        return None
    s, e = text.rfind(START), text.rfind(END)
    if s != -1 and e > s:
        value = _last_json_object(text[s + len(START):e])
        if value is not None:
            return value
    fenced = FENCED.findall(text)
    for block in reversed(fenced):
        try:
            value = json.loads(block)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return _last_json_object(text)


def _str_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value else []


def _risk(value) -> str:
    return value if value in ("low", "medium", "high") else "high"


def parse_build(text: str) -> dict:
    data = extract_json(text) or {}
    status = data.get("status")
    if status not in ("done", "blocked", "failed"):
        status = "failed"  # no valid status means we can't trust the run
    passed = data.get("tests_passed")
    return {
        "status": status,
        "summary": str(data.get("summary") or ("No result block found in the agent's output."
                                                if not data else "")),
        "files_changed": _str_list(data.get("files_changed")),
        "tests_run": _str_list(data.get("tests_run")),
        "tests_passed": passed if isinstance(passed, bool) else None,
        "decisions": _str_list(data.get("decisions")),
        "open_questions": _str_list(data.get("open_questions")),
        "next_step": str(data.get("next_step") or ""),
        "risk": _risk(data.get("risk")),
        "parsed": bool(data),
    }


def parse_review(text: str) -> dict:
    data = extract_json(text) or {}
    verdict = data.get("verdict")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"  # unparseable review never approves
    issues = []
    for item in data.get("blocking_issues") or []:
        if isinstance(item, dict):
            issues.append({k: str(item.get(k, "")) for k in ("file", "line", "issue", "fix")})
        else:
            issues.append({"file": "", "line": "", "issue": str(item), "fix": ""})
    if verdict == "approve" and issues:
        verdict = "request_changes"  # blocking issues outrank an 'approve'
    return {
        "verdict": verdict,
        "blocking_issues": issues,
        "suggestions": _str_list(data.get("suggestions")),
        "risk": _risk(data.get("risk")),
        "summary": str(data.get("summary") or ("Reviewer output had no result block."
                                                if not data else "")),
        "parsed": bool(data),
    }


def parse_plan(text: str) -> dict:
    data = extract_json(text) or {}
    tasks = []
    for i, t in enumerate(data.get("tasks") or []):
        if not isinstance(t, dict) or not t.get("title"):
            continue
        size = t.get("size") if t.get("size") in ("S", "M", "L") else "M"
        deps = [int(d) for d in (t.get("depends_on") or []) if str(d).isdigit()]
        tasks.append({
            "index": i,
            "title": str(t["title"])[:200],
            "body": str(t.get("body") or ""),
            "size": size,
            "depends_on": deps,
            "agent": t.get("agent") or None,
        })
    return {
        "title": str(data.get("title") or "Spec"),
        "spec_markdown": str(data.get("spec_markdown") or ""),
        "tasks": tasks,
        "parsed": bool(data),
    }
