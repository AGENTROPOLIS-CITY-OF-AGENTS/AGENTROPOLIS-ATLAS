#!/usr/bin/env python3
"""No-network regression checks for the vendored loop baseline.

Fails when any HTML file references a remote loop-baseline script, when the
local file digest or git blob drifts from the fleet pin, or when the Pages
publish tree (git archive of HEAD, the tree actions/checkout publishes) does
not contain that script at the path index.html references.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL_SCRIPT = "agentropolis-loop-baseline.js"
EXPECTED_SHA256 = "df28604ae9462594df48aa6fa05d9a77a3ca02e2f74c29aa3ba264da6e4d7224"
EXPECTED_BLOB = "15254b442f33e009f4c78a1c19568e75ea2121b2"
PUBLISH = REPO / "build" / "publish"
SCRIPT_SRC = re.compile(
    r"<script\b[^>]*\bsrc\s*=\s*(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)
REMOTE_HOST = "agentropolis-city-of-agents.github.io"
REMOTE_PATH = "/AGENTROPOLIS-DESIGN-SYSTEM/js/loop-baseline.js"
REMOTE_SCRIPT = f"https://{REMOTE_HOST}{REMOTE_PATH}"
SKIP_DIRS = {".git", "build", "node_modules"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def is_remote(src: str) -> bool:
    value = src.strip().lower()
    return value.startswith(("http://", "https://", "//"))


def is_forbidden_script(src: str) -> bool:
    value = src.strip()
    lower = value.lower()
    if is_remote(value) and "loop-baseline" in lower:
        return True
    if "github.io" in lower:
        return True
    if "agentropolis-design-system" in lower and "loop-baseline" in lower:
        return True
    if lower in {REMOTE_SCRIPT.lower(), f"//{REMOTE_HOST}{REMOTE_PATH}".lower()}:
        return True
    return False


def violations_in_html(text: str, name: str) -> list[str]:
    found: list[str] = []
    for match in SCRIPT_SRC.finditer(text):
        src = match.group(2).strip()
        if is_forbidden_script(src):
            found.append(f"{name}: remote script src {src}")
        elif "loop-baseline" in src.lower() and not _is_local_baseline(src):
            found.append(f"{name}: unexpected loop-baseline src {src}")
    if REMOTE_SCRIPT in text:
        found.append(f"{name}: contains remote loop-baseline URL")
    return found


def _is_local_baseline(src: str) -> bool:
    normalized = src.strip().split("?", 1)[0].split("#", 1)[0]
    return normalized in {
        "./agentropolis-loop-baseline.js",
        "agentropolis-loop-baseline.js",
        "/agentropolis-loop-baseline.js",
    }


def self_check() -> None:
    remote = (
        '<script src="https://agentropolis-city-of-agents.github.io/'
        'AGENTROPOLIS-DESIGN-SYSTEM/js/loop-baseline.js" defer></script>'
    )
    local = '<script src="./agentropolis-loop-baseline.js" defer></script>'
    if not violations_in_html(remote, "sample.html"):
        raise SystemExit("SELF_CHECK failed: remote loop-baseline script was accepted")
    if violations_in_html(local, "index.html"):
        raise SystemExit("SELF_CHECK failed: local loop-baseline script was rejected")
    if not is_forbidden_script(REMOTE_SCRIPT):
        raise SystemExit("SELF_CHECK failed: pinned remote URL was accepted")
    print("SELF_CHECK=pass")


def iter_html(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.html"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


def scan_tree_for_remote_script(root: Path) -> list[str]:
    """Flag the remote script URL in tracked site files. Tests may name it."""
    problems: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS or part == "tests" for part in rel.parts):
            continue
        if path.suffix.lower() not in {".html", ".js", ".css", ".md", ".yml", ".yaml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if REMOTE_SCRIPT in text or f"{REMOTE_HOST}{REMOTE_PATH}" in text:
            problems.append(f"{rel.as_posix()}: references remote loop-baseline script URL")
        for match in SCRIPT_SRC.finditer(text):
            src = match.group(2).strip()
            if is_forbidden_script(src):
                problems.append(f"{rel.as_posix()}: remote script src {src}")
    return problems


def pages_gate(root: Path) -> list[str]:
    problems: list[str] = []
    for name in ("index.html", "styles.css", "script.js"):
        if not (root / name).is_file():
            problems.append(f"pages gate: missing {name}")
    script = root / "script.js"
    if script.is_file() and script.stat().st_size > 358400:
        problems.append(f"pages gate: script.js is {script.stat().st_size} bytes")
    shell = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (root / "index.html", root / "script.js")
        if path.is_file()
    )
    if re.search(r"three|@react-three|drei", shell, re.IGNORECASE):
        problems.append("pages gate: three.js marker present")
    if re.search(r"<(video|audio)[^>]*autoplay", shell, re.IGNORECASE):
        problems.append("pages gate: autoplay media present")
    return problems


def stage_publish(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    raw = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=REPO)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        dest_root = dest.resolve()
        for member in archive.getmembers():
            target = (dest / member.name).resolve()
            if target != dest_root and dest_root not in target.parents:
                raise SystemExit(f"unsafe archive path: {member.name}")
            if member.issym() or member.islnk():
                raise SystemExit(f"archive link refused: {member.name}")
        archive.extractall(dest)


def resolve_src(publish: Path, html: Path, src: str) -> Path:
    if src.startswith("/"):
        candidate = (publish / src.lstrip("/")).resolve()
    else:
        candidate = (html.parent / src).resolve()
    publish_root = publish.resolve()
    if candidate != publish_root and publish_root not in candidate.parents:
        raise ValueError(f"{src} escapes publish root")
    return candidate


def main() -> int:
    self_check()
    problems: list[str] = []

    local = REPO / LOCAL_SCRIPT
    if not local.is_file():
        problems.append(f"missing {LOCAL_SCRIPT}")
    else:
        digest = sha256_file(local)
        print(f"SHA256={digest}")
        if digest != EXPECTED_SHA256:
            problems.append(f"sha256 {digest} != {EXPECTED_SHA256}")
        blob = subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{LOCAL_SCRIPT}"], cwd=REPO, text=True
        ).strip()
        worktree_blob = subprocess.check_output(
            ["git", "hash-object", LOCAL_SCRIPT], cwd=REPO, text=True
        ).strip()
        print(f"BLOB_SHA={blob}")
        print(f"WORKTREE_BLOB={worktree_blob}")
        if blob != EXPECTED_BLOB:
            problems.append(f"blob {blob} != {EXPECTED_BLOB}")
        if worktree_blob != blob:
            problems.append("worktree script differs from HEAD blob")

    for html in iter_html(REPO):
        problems.extend(violations_in_html(html.read_text(encoding="utf-8"), html.relative_to(REPO).as_posix()))
    problems.extend(scan_tree_for_remote_script(REPO))
    problems.extend(pages_gate(REPO))

    stage_publish(PUBLISH)
    index = PUBLISH / "index.html"
    if not index.is_file():
        problems.append("publish tree missing index.html")
    else:
        text = index.read_text(encoding="utf-8")
        srcs = [match.group(2).strip() for match in SCRIPT_SRC.finditer(text)]
        print("HTML_SCRIPT_SRCS=" + ",".join(srcs))
        baseline_srcs = [src for src in srcs if "loop-baseline" in src.lower()]
        if baseline_srcs != ["./agentropolis-loop-baseline.js"]:
            problems.append(f"index.html baseline srcs {baseline_srcs}")
        for src in baseline_srcs:
            try:
                published = resolve_src(PUBLISH, index, src)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            rel = published.relative_to(PUBLISH.resolve()).as_posix()
            print(f"PUBLISH_SCRIPT={rel}")
            if not published.is_file():
                problems.append(f"publish output missing {rel}")
                continue
            published_digest = sha256_file(published)
            print(f"PUBLISH_SHA256={published_digest}")
            if published_digest != EXPECTED_SHA256:
                problems.append(f"publish sha256 {published_digest} != {EXPECTED_SHA256}")

    if problems:
        print(f"REMOTE_SCRIPT_REFS={len(problems)}")
        for problem in problems:
            print(f"FAIL {problem}")
        return 1

    print("REMOTE_SCRIPT_REFS=0")
    print("PAGES_GATE=pass")
    print("PUBLISH_ROOT=build/publish")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
