"""Push a merge commit with worker-side ``git`` (GitLab's Commits API cannot make one).

Runs in the worker, never in the sandbox, and never runs repository code: a blobless shallow
fetch of the parents, then plumbing only (``read-tree``/``hash-object``/``update-index``/
``write-tree``/``commit-tree``) and a push. The token travels as an ``http.extraHeader`` on the
command line only (like the sandbox clone), never in a URL, remote or config file.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from collections.abc import Sequence

from app.platforms.base import PlatformError
from app.platforms.finishing import FileChange, PushRejected

GIT_TIMEOUT_S = 300
BOT_NAME = "HootPR"
BOT_EMAIL = "hootpr@users.noreply.local"


def _run(
    argv: list[str], cwd: str, *, secret: str, stdin: bytes | None = None, env: dict[str, str]
) -> str:
    try:
        p = subprocess.run(  # noqa: S603 - argv list, no shell
            argv, cwd=cwd, input=stdin, capture_output=True, timeout=GIT_TIMEOUT_S, env=env,
            check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlatformError(0, f"git failed: {type(exc).__name__}") from exc
    if p.returncode != 0:
        err = p.stderr.decode(errors="replace").replace(secret, "***")[:500] if secret else ""
        if "non-fast-forward" in err or "rejected" in err or "stale info" in err:
            raise PushRejected(err)
        raise PlatformError(0, f"git {argv[3] if len(argv) > 3 else ''} failed: {err}")
    return p.stdout.decode(errors="replace").strip()


def push_merge_commit(
    *,
    url: str,
    username: str,
    token: str,
    branch: str,
    parents: Sequence[str],
    tree_base: str,
    message: str,
    changes: Sequence[FileChange],
) -> str:
    git = shutil.which("git")
    if git is None:
        raise PlatformError(501, "git is not installed in the worker image")
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    header = f"http.extraHeader=Authorization: Basic {auth}"
    work = tempfile.mkdtemp(prefix="hootpr-push-")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": work,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_INDEX_FILE": f"{work}/index.tmp",
        "GIT_AUTHOR_NAME": BOT_NAME,
        "GIT_AUTHOR_EMAIL": BOT_EMAIL,
        "GIT_COMMITTER_NAME": BOT_NAME,
        "GIT_COMMITTER_EMAIL": BOT_EMAIL,
    }
    try:
        _run([git, "-C", work, "init", "-q", "--bare"], work, secret=auth, env=env)
        wants = list(dict.fromkeys([*parents, tree_base]))
        _run(
            [git, "-C", work, "-c", header, "fetch", "-q", "--no-tags", "--depth=1",
             "--filter=blob:none", url, *wants],
            work, secret=auth, env=env,
        )  # fmt: skip
        _run([git, "-C", work, "read-tree", tree_base], work, secret=auth, env=env)
        for ch in changes:
            if ch.content is None:
                _run(
                    [git, "-C", work, "update-index", "--force-remove", "--", ch.path],
                    work, secret=auth, env=env,
                )  # fmt: skip
                continue
            blob = _run(
                [git, "-C", work, "hash-object", "-w", "--stdin"],
                work, secret=auth, stdin=ch.content, env=env,
            )  # fmt: skip
            mode = "100755" if ch.executable else "100644"
            entry = f"{mode},{blob},{ch.path}"
            _run(
                [git, "-C", work, "update-index", "--add", "--cacheinfo", entry],
                work, secret=auth, env=env,
            )  # fmt: skip
        tree = _run([git, "-C", work, "write-tree", "--missing-ok"], work, secret=auth, env=env)
        argv = [git, "-C", work, "commit-tree", tree, "-m", message]
        for parent in parents:
            argv += ["-p", parent]
        sha = _run(argv, work, secret=auth, env=env)
        _run(
            [git, "-C", work, "-c", header, "push", "-q", url, f"{sha}:refs/heads/{branch}"],
            work, secret=auth, env=env,
        )  # fmt: skip
        return sha
    finally:
        shutil.rmtree(work, ignore_errors=True)
