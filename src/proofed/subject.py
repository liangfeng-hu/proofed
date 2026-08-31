from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".proofed",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}


class SubjectError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    """RFC 8785-equivalent for Proofed's fixed-key, integer-only v0.1 domain."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(root: Path, args: list[str], *, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SubjectError(message or f"git {' '.join(args)} failed")
    return completed.stdout if binary else completed.stdout.decode("utf-8").strip()


def _is_ignored(relative: str) -> bool:
    parts = Path(relative).parts
    return any(part in IGNORED_DIRS for part in parts)


def _safe_relative_file(root: Path, relative: str) -> Path:
    candidate = root / relative
    resolved_parent = candidate.parent.resolve()
    try:
        resolved_parent.relative_to(root.resolve())
    except ValueError as exc:
        raise SubjectError(f"path escapes repository: {relative}") from exc
    return candidate


def _entry_descriptor(root: Path, relative: str) -> dict[str, str]:
    path = _safe_relative_file(root, relative)
    if path.is_symlink():
        return {"path": relative.replace(os.sep, "/"), "symlink": os.readlink(path)}
    if not path.is_file():
        return {"path": relative.replace(os.sep, "/"), "kind": "non-regular"}
    return {
        "path": relative.replace(os.sep, "/"),
        "sha256": sha256_file(path),
    }


def _filesystem_entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().encode("utf-8")):
        relative = path.relative_to(root).as_posix()
        if _is_ignored(relative):
            continue
        if path.is_file() or path.is_symlink():
            entries.append(_entry_descriptor(root, relative))
    return entries


def repository_state(root: Path) -> dict[str, Any]:
    root = root.resolve()
    try:
        inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"]) == "true"
    except SubjectError:
        inside = False
    if not inside:
        snapshot = {"entries": _filesystem_entries(root)}
        descriptor = {
            "descriptorVersion": "0.1",
            "commitOid": None,
            "treeOid": None,
            "workspacePatchSha256": sha256_bytes(canonical_json(snapshot)),
        }
        return descriptor

    try:
        commit_oid = str(_run_git(root, ["rev-parse", "HEAD"]))
        tree_oid = str(_run_git(root, ["rev-parse", "HEAD^{tree}"]))
        tracked_patch = _run_git(
            root,
            [
                "diff",
                "--binary",
                "--no-ext-diff",
                "HEAD",
                "--",
                ".",
                ":(exclude).proofed/**",
                ":(exclude)**/__pycache__/**",
                ":(exclude).pytest_cache/**",
                ":(exclude)node_modules/**",
            ],
            binary=True,
        )
    except SubjectError:
        commit_oid = None
        tree_oid = None
        tracked_patch = b""

    raw_untracked = _run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"], binary=True)
    untracked_names = [
        item.decode("utf-8", errors="surrogateescape")
        for item in raw_untracked.split(b"\0")
        if item
    ]
    untracked = [
        _entry_descriptor(root, item)
        for item in sorted(untracked_names, key=lambda value: value.encode("utf-8"))
        if not _is_ignored(item)
    ]
    patch_descriptor = {
        "trackedPatchSha256": sha256_bytes(tracked_patch),
        "untracked": untracked,
    }
    return {
        "descriptorVersion": "0.1",
        "commitOid": commit_oid,
        "treeOid": tree_oid,
        "workspacePatchSha256": sha256_bytes(canonical_json(patch_descriptor)),
    }


def current_subject(root: Path) -> dict[str, Any]:
    descriptor = repository_state(root)
    digest = sha256_bytes(canonical_json(descriptor))
    return {
        "name": "repository-state",
        "digest": {"sha256": digest},
        "descriptor": descriptor,
    }
