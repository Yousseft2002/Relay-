"""Git worktrees: each task gets its own folder and branch, so agents never collide."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    exe = shutil.which("git")
    if exe is None:
        raise GitError("git isn't installed or isn't on PATH")
    proc = subprocess.run([exe, *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[-400:]}")
    return proc


def branch_for(issue: int) -> str:
    return f"relay/issue-{issue}"


def remote_branch_exists(repo_dir: Path, branch: str) -> bool:
    proc = git(["ls-remote", "--heads", "origin", branch], repo_dir, check=False)
    return bool(proc.stdout.strip())


def prepare_worktree(repo_dir: Path, root: Path, branch: str, base: str) -> Path:
    """Create (or refresh) the worktree for `branch`. New branches start from origin/base."""
    path = root / branch.replace("/", "-")
    git(["fetch", "origin", base], repo_dir)
    if path.exists():
        git(["fetch", "origin", branch], repo_dir, check=False)
        if remote_branch_exists(repo_dir, branch):
            git(["pull", "--ff-only", "origin", branch], path, check=False)
        return path

    root.mkdir(parents=True, exist_ok=True)
    git(["worktree", "prune"], repo_dir, check=False)
    if remote_branch_exists(repo_dir, branch):
        git(["fetch", "origin", f"{branch}:{branch}"], repo_dir, check=False)
        git(["worktree", "add", str(path), branch], repo_dir)
    else:
        local = git(["rev-parse", "--verify", "--quiet", branch], repo_dir, check=False)
        if local.returncode == 0:
            git(["worktree", "add", str(path), branch], repo_dir)
        else:
            git(["worktree", "add", "-b", branch, str(path), f"origin/{base}"], repo_dir)
    return path


def commit_and_push(path: Path, branch: str, message: str) -> bool:
    """Commit everything in the worktree and push. Returns False if nothing changed."""
    git(["add", "-A"], path)
    staged = git(["diff", "--cached", "--quiet"], path, check=False)
    if staged.returncode == 0:
        return False
    git(["commit", "-m", message], path)
    git(["push", "-u", "origin", branch], path)
    return True


def changed_files(path: Path, base: str) -> list[str]:
    proc = git(["diff", "--name-only", f"origin/{base}...HEAD"], path, check=False)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def remove_worktree(repo_dir: Path, path: Path) -> None:
    if path.exists():
        git(["worktree", "remove", "--force", str(path)], repo_dir, check=False)
