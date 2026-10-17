#!/usr/bin/env python3
"""No-network regression checks for the vendored loop baseline.

Fails when any HTML file references a remote loop-baseline script, when the
local file digest or git blob drifts from the fleet pin, when the vendored
script tag loses its pinned SHA-384 integrity, or when the Pages allowlist
(_site, the tree this workflow uploads) is missing that script or contains
tests, services, docs, policies, skills, or .agentropolis.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONUNBUFFERED"] = "1"
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass

REPO = Path(__file__).resolve().parents[1]
LOCAL_SCRIPT = "agentropolis-loop-baseline.js"
EXPECTED_SHA256 = "df28604ae9462594df48aa6fa05d9a77a3ca02e2f74c29aa3ba264da6e4d7224"
EXPECTED_BLOB = "15254b442f33e009f4c78a1c19568e75ea2121b2"
EXPECTED_SRI_B64 = "YXPNohgGheUM32mm6qMBBKuRXhwU5Wkrwu9dgTmQBJRRIY0TdgcgxoEtvhxgTaqY"
EXPECTED_INTEGRITY = f"sha384-{EXPECTED_SRI_B64}"
PUBLISH = REPO / "_site"
SEED = (
    "index.html",
    "styles.css",
    "script.js",
    LOCAL_SCRIPT,
)
SCAN_FILES = ("index.html", "styles.css", "script.js")
FORBIDDEN_ROOTS = ("tests", "services", "docs", "policies", "skills", ".agentropolis")
SCRIPT_SRC = re.compile(
    r"<script\b[^>]*\bsrc\s*=\s*(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)
SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
ATTR_REF = re.compile(
    r"""\b(?:src|href|poster)\s*=\s*(['"])([^'"]+)\1""",
    re.IGNORECASE,
)
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", re.IGNORECASE)
CSS_IMPORT = re.compile(
    r"""@import\s+(?:url\(\s*)?(['"])([^'"]+)\1""",
    re.IGNORECASE,
)
INTEGRITY_ATTR = re.compile(
    r"""\bintegrity\s*=\s*(['"])([^'"]+)\1""",
    re.IGNORECASE,
)
CROSSORIGIN_ATTR = re.compile(
    r"""\bcrossorigin\s*=\s*(['"])([^'"]+)\1""",
    re.IGNORECASE,
)
REMOTE_HOST = "agentropolis-city-of-agents.github.io"
REMOTE_PATH = "/AGENTROPOLIS-DESIGN-SYSTEM/js/loop-baseline.js"
REMOTE_SCRIPT = f"https://{REMOTE_HOST}{REMOTE_PATH}"
SKIP_DIRS = {".git", "build", "node_modules", "_site"}
WORKFLOW = REPO / ".github" / "workflows" / "pages.yml"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def openssl_sha384_b64(path: Path) -> str:
    binary = subprocess.check_output(
        ["openssl", "dgst", "-sha384", "-binary", str(path)],
    )
    encoded = subprocess.check_output(["openssl", "base64", "-A"], input=binary)
    return encoded.decode().strip()


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


def baseline_script_tags(text: str) -> list[str]:
    tags: list[str] = []
    for tag in SCRIPT_TAG.findall(text):
        match = SCRIPT_SRC.search(tag)
        if match and "loop-baseline" in match.group(2).lower():
            tags.append(tag)
    return tags


def sri_problems(text: str, name: str) -> list[str]:
    problems: list[str] = []
    tags = baseline_script_tags(text)
    if len(tags) != 1:
        problems.append(f"{name}: expected one vendored baseline script tag, found {len(tags)}")
        return problems
    tag = tags[0]
    integrity = [match.group(2) for match in INTEGRITY_ATTR.finditer(tag)]
    if integrity != [EXPECTED_INTEGRITY]:
        problems.append(f"{name}: integrity {integrity} != {EXPECTED_INTEGRITY}")
    crossorigin = [match.group(2).lower() for match in CROSSORIGIN_ATTR.finditer(tag)]
    if crossorigin != ["anonymous"]:
        problems.append(f"{name}: crossorigin {crossorigin} != ['anonymous']")
    return problems


def iter_resource_refs(text: str) -> list[str]:
    found = [match.group(2) for match in ATTR_REF.finditer(text)]
    found.extend(match.group(2) for match in CSS_URL.finditer(text))
    found.extend(match.group(2) for match in CSS_IMPORT.finditer(text))
    return found


def classify_ref(raw: str) -> tuple[str, str]:
    value = raw.strip()
    if not value:
        return "skip", ""
    lowered = value.lower()
    if lowered.startswith(("#", "data:", "mailto:", "javascript:", "blob:")):
        return "skip", ""
    if is_remote(value) or value.startswith("//"):
        return "remote", value
    path = value.split("#", 1)[0].split("?", 1)[0]
    if path.startswith("./"):
        path = path[2:]
    if path.startswith("/"):
        return "absolute", path
    if not path or path.endswith("/"):
        return "skip", path
    parts = Path(path).parts
    if ".." in parts:
        return "escape", path
    if parts[0] in FORBIDDEN_ROOTS:
        return "forbid", path
    candidate = (REPO / path).resolve()
    root = REPO.resolve()
    if candidate != root and root not in candidate.parents:
        return "escape", path
    if not candidate.is_file():
        return "missing", path
    return "local", path


def expected_publish_files(*, echo: bool) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    files: list[str] = list(SEED)
    seen = set(files)
    for name in SCAN_FILES:
        text = (REPO / name).read_text(encoding="utf-8")
        refs = iter_resource_refs(text)
        if echo and not refs:
            print(f"GREP_REF file={name} raw=- class=none path=-")
        for raw in refs:
            decision, rel = classify_ref(raw)
            if echo:
                print(f"GREP_REF file={name} raw={raw} class={decision} path={rel or '-'}")
            if decision == "skip":
                continue
            if decision == "local":
                if rel not in seen:
                    files.append(rel)
                    seen.add(rel)
                continue
            problems.append(f"{name}: {decision} reference {raw}")
    return files, problems


def self_check() -> None:
    remote = (
        '<script src="https://agentropolis-city-of-agents.github.io/'
        'AGENTROPOLIS-DESIGN-SYSTEM/js/loop-baseline.js" defer></script>'
    )
    local = '<script src="./agentropolis-loop-baseline.js" defer></script>'
    pinned = (
        '<script src="./agentropolis-loop-baseline.js" '
        f'integrity="{EXPECTED_INTEGRITY}" crossorigin="anonymous" defer></script>'
    )
    if not violations_in_html(remote, "sample.html"):
        raise SystemExit("SELF_CHECK failed: remote loop-baseline script was accepted")
    if violations_in_html(local, "index.html"):
        raise SystemExit("SELF_CHECK failed: local loop-baseline script was rejected")
    if violations_in_html(pinned, "index.html"):
        raise SystemExit("SELF_CHECK failed: SRI baseline script was rejected")
    if not is_forbidden_script(REMOTE_SCRIPT):
        raise SystemExit("SELF_CHECK failed: pinned remote URL was accepted")
    if not sri_problems(local, "sample.html"):
        raise SystemExit("SELF_CHECK failed: baseline script without SRI was accepted")
    if sri_problems(pinned, "sample.html"):
        raise SystemExit("SELF_CHECK failed: pinned SRI tag was rejected")
    wrong = pinned.replace(EXPECTED_SRI_B64, "A" * len(EXPECTED_SRI_B64))
    if not sri_problems(wrong, "sample.html"):
        raise SystemExit("SELF_CHECK failed: wrong integrity was accepted")
    if classify_ref(REMOTE_SCRIPT)[0] != "remote":
        raise SystemExit("SELF_CHECK failed: remote URL was not classified remote")
    if classify_ref("#atlas")[0] != "skip":
        raise SystemExit("SELF_CHECK failed: fragment reference was not skipped")
    if classify_ref("./styles.css") != ("local", "styles.css"):
        raise SystemExit("SELF_CHECK failed: local stylesheet was not classified local")
    if classify_ref("tests/vendor_baseline_regression.py")[0] != "forbid":
        raise SystemExit("SELF_CHECK failed: tests reference was publishable")
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
    for name in ("index.html", "styles.css", "script.js", LOCAL_SCRIPT):
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


def resolve_src(publish: Path, html: Path, src: str) -> Path:
    if src.startswith("/"):
        candidate = (publish / src.lstrip("/")).resolve()
    else:
        candidate = (html.parent / src).resolve()
    publish_root = publish.resolve()
    if candidate != publish_root and publish_root not in candidate.parents:
        raise ValueError(f"{src} escapes publish root")
    return candidate


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def stage_script_from_workflow(text: str) -> str:
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "- name: Stage public shell"),
        None,
    )
    if start is None:
        raise ValueError("pages.yml: missing Stage public shell step")
    run_at = next(
        (index for index in range(start, min(start + 8, len(lines))) if lines[index].strip() == "run: |"),
        None,
    )
    if run_at is None or run_at + 1 >= len(lines):
        raise ValueError("pages.yml: stage step has no run block")
    indent = len(lines[run_at + 1]) - len(lines[run_at + 1].lstrip(" "))
    if indent < 2:
        raise ValueError("pages.yml: stage run block is not indented")
    body: list[str] = []
    for line in lines[run_at + 1 :]:
        if line.strip() == "":
            body.append("")
            continue
        if not line.startswith(" " * indent):
            break
        body.append(line[indent:])
    script = "\n".join(body).strip() + "\n"
    if not script.strip():
        raise ValueError("pages.yml: stage run block is empty")
    return script


def check_pages_workflow(text: str) -> tuple[list[str], str]:
    problems: list[str] = []
    paths = re.search(r"(?m)^\s*paths:\s*\n((?:\s+- .+\n)+)", text)
    block = paths.group(1) if paths else ""
    for name in (*SEED, ".github/workflows/pages.yml"):
        if f'- "{name}"' not in block:
            problems.append(f"pages.yml: push paths missing {name}")
    qualify = re.search(
        r"(?m)^\s*run:\s*python3 tests/vendor_baseline_regression\.py\s*$",
        text,
    )
    upload = re.search(r"actions/upload-pages-artifact@", text)
    if qualify is None:
        problems.append("pages.yml: deploy job does not run the fail-closed regression")
    elif upload is None or qualify.start() > upload.start():
        problems.append("pages.yml: regression does not run before upload")
    if upload is None:
        problems.append("pages.yml: missing upload-pages-artifact")
    if not re.search(r"(?m)^[ \t]*path:[ \t]*_site[ \t]*$", text):
        problems.append("pages.yml: upload path is not _site")
    if re.search(r"(?m)^[ \t]*path:[ \t]*\.[ \t]*$", text):
        problems.append("pages.yml: upload path is the repo root")
    try:
        script = stage_script_from_workflow(text)
    except ValueError as exc:
        problems.append(str(exc))
        script = ""
    needles = (
        "set -euo pipefail",
        "rm -rf _site",
        "mkdir -p _site",
        "cp index.html styles.css script.js agentropolis-loop-baseline.js _site/",
        "python3 tests/vendor_baseline_regression.py --stage-site",
        "test ! -e _site/tests",
        "test ! -e _site/services",
        "test ! -e _site/docs",
        "test ! -e _site/policies",
        "test ! -e _site/skills",
        "test ! -e _site/.agentropolis",
    )
    for needle in needles:
        if needle not in script:
            problems.append(f"pages.yml: stage script missing {needle}")
    return problems, script


def site_files(dest: Path) -> list[str]:
    return sorted(
        path.relative_to(dest).as_posix()
        for path in dest.rglob("*")
        if path.is_file()
    )


def verify_site(dest: Path, expected: list[str]) -> list[str]:
    problems: list[str] = []
    if dest.is_symlink() or not dest.is_dir():
        return ["_site is not a real directory"]
    actual = site_files(dest)
    print("SITE_FILES=" + ",".join(actual))
    if actual != sorted(expected):
        problems.append(f"_site files {actual} != allowlist {sorted(expected)}")
    for name in FORBIDDEN_ROOTS:
        if (dest / name).exists():
            problems.append(f"_site contains {name}")
    for rel in actual:
        if rel.split("/", 1)[0] in FORBIDDEN_ROOTS:
            problems.append(f"_site published forbidden path {rel}")
    for rel in expected:
        src = REPO / rel
        published = dest / rel
        if not published.is_file():
            problems.append(f"_site missing {rel}")
            continue
        if src.read_bytes() != published.read_bytes():
            problems.append(f"_site {rel} bytes differ from the repo file")
    index = dest / "index.html"
    if index.is_file():
        text = index.read_text(encoding="utf-8")
        problems.extend(sri_problems(text, "_site/index.html"))
        srcs = [match.group(2).strip() for match in SCRIPT_SRC.finditer(text)]
        print("HTML_SCRIPT_SRCS=" + ",".join(srcs))
        baseline_srcs = [src for src in srcs if "loop-baseline" in src.lower()]
        if baseline_srcs != ["./agentropolis-loop-baseline.js"]:
            problems.append(f"_site/index.html baseline srcs {baseline_srcs}")
        for src in baseline_srcs:
            try:
                published = resolve_src(dest, index, src)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            rel = published.relative_to(dest.resolve()).as_posix()
            print(f"PUBLISH_SCRIPT={rel}")
            if not published.is_file():
                problems.append(f"publish output missing {rel}")
                continue
            published_digest = sha256_file(published)
            published_blob = subprocess.check_output(
                ["git", "hash-object", str(published)],
                cwd=REPO,
                text=True,
            ).strip()
            print(f"PUBLISH_SHA256={published_digest}")
            print(f"PUBLISH_BLOB={published_blob}")
            if published_digest != EXPECTED_SHA256:
                problems.append(f"publish sha256 {published_digest} != {EXPECTED_SHA256}")
            if published_blob != EXPECTED_BLOB:
                problems.append(f"publish blob {published_blob} != {EXPECTED_BLOB}")
    return problems


def copy_missing(dest: Path, expected: list[str]) -> list[str]:
    problems: list[str] = []
    for rel in expected:
        if rel in SEED:
            continue
        target = dest / rel
        source = REPO / rel
        if not source.is_file():
            problems.append(f"cannot copy missing reference {rel}")
            continue
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"COPIED_REFERENCE={rel}")
    return problems


def check_pins() -> list[str]:
    problems: list[str] = []
    local = REPO / LOCAL_SCRIPT
    if not local.is_file():
        problems.append(f"missing {LOCAL_SCRIPT}")
        return problems
    digest = sha256_file(local)
    print(f"SHA256={digest}")
    if digest != EXPECTED_SHA256:
        problems.append(f"sha256 {digest} != {EXPECTED_SHA256}")
    blob = subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{LOCAL_SCRIPT}"],
        cwd=REPO,
        text=True,
    ).strip()
    worktree_blob = subprocess.check_output(
        ["git", "hash-object", LOCAL_SCRIPT],
        cwd=REPO,
        text=True,
    ).strip()
    print(f"BLOB_SHA={blob}")
    print(f"WORKTREE_BLOB={worktree_blob}")
    if blob != EXPECTED_BLOB:
        problems.append(f"blob {blob} != {EXPECTED_BLOB}")
    if worktree_blob != blob:
        problems.append("worktree script differs from HEAD blob")
    openssl_b64 = openssl_sha384_b64(local)
    python_b64 = base64.b64encode(hashlib.sha384(local.read_bytes()).digest()).decode()
    print(f"SHA384_HEX={hashlib.sha384(local.read_bytes()).hexdigest()}")
    print(f"OPENSSL_SHA384_B64={openssl_b64}")
    print(f"PYTHON_SHA384_B64={python_b64}")
    if openssl_b64 != python_b64:
        problems.append("openssl sha384 does not match hashlib sha384")
    if openssl_b64 != EXPECTED_SRI_B64:
        problems.append(f"openssl sha384 {openssl_b64} != {EXPECTED_SRI_B64}")
    index = REPO / "index.html"
    problems.extend(sri_problems(index.read_text(encoding="utf-8"), "index.html"))
    if not problems:
        print(f"SRI={EXPECTED_INTEGRITY}")
    return problems


def check_tree() -> list[str]:
    problems: list[str] = []
    for html in iter_html(REPO):
        problems.extend(
            violations_in_html(
                html.read_text(encoding="utf-8"),
                html.relative_to(REPO).as_posix(),
            )
        )
    problems.extend(scan_tree_for_remote_script(REPO))
    problems.extend(pages_gate(REPO))
    return problems


def require_seeds(dest: Path) -> list[str]:
    if not dest.exists() or dest.is_symlink() or not dest.is_dir():
        return ["_site is not a real directory created by the stage script"]
    problems: list[str] = []
    for name in SEED:
        if not (dest / name).is_file():
            problems.append(f"_site missing seeded file {name}")
    return problems


def stage_site_cli() -> int:
    dest = PUBLISH.resolve()
    root = REPO.resolve()
    if dest == root or root not in dest.parents:
        print("FAIL refusing to stage outside _site")
        return 1
    problems = require_seeds(PUBLISH)
    expected, discovered = expected_publish_files(echo=False)
    problems.extend(discovered)
    if not problems:
        problems.extend(copy_missing(PUBLISH, expected))
        problems.extend(verify_site(PUBLISH, expected))
    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    print("STAGE_SITE=pass")
    return 0


def report(problems: list[str]) -> int:
    print(f"REMOTE_SCRIPT_REFS={len(problems)}")
    for problem in problems:
        print(f"FAIL {problem}")
    return 1


def full_check() -> int:
    self_check()
    problems = check_pins()
    problems.extend(check_tree())
    workflow_problems, script = check_pages_workflow(workflow_text())
    problems.extend(workflow_problems)
    _, ref_problems = expected_publish_files(echo=True)
    problems.extend(ref_problems)
    if problems:
        return report(problems)
    print("STAGE_SCRIPT=pages.yml")
    completed = subprocess.run(["bash", "-c", script], cwd=REPO)
    print(f"STAGE_SCRIPT_EXIT={completed.returncode}")
    if completed.returncode != 0:
        return report([f"pages stage script exited {completed.returncode}"])
    expected, discovered = expected_publish_files(echo=False)
    problems.extend(discovered)
    problems.extend(verify_site(PUBLISH, expected))
    if problems:
        return report(problems)
    print("REMOTE_SCRIPT_REFS=0")
    print("PAGES_GATE=pass")
    print("PUBLISH_ROOT=_site")
    print("OK")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--stage-site"]:
        return stage_site_cli()
    if argv:
        print(f"unknown arguments: {' '.join(argv)}", file=sys.stderr)
        return 2
    return full_check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
