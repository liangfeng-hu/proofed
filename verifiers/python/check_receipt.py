#!/usr/bin/env python3
"""Kernel-free SRR verifier. Uses only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
TEST_RESULT_TYPE = "https://in-toto.io/attestation/test-result/v0.1"
COMPLETION_TYPE = "urn:uuid:7ec9a0e8-9d21-4b8c-9bdd-11e1ab3c87cf"
IGNORED = {".git", ".proofed", ".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__", "node_modules"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def ignored(relative: str) -> bool:
    return any(part in IGNORED for part in Path(relative).parts)


def entry(root: Path, relative: str) -> dict[str, str]:
    path = root / relative
    if path.is_symlink():
        return {"path": Path(relative).as_posix(), "symlink": os.readlink(path)}
    if path.is_file():
        return {"path": Path(relative).as_posix(), "sha256": file_digest(path)}
    return {"path": Path(relative).as_posix(), "kind": "non-regular"}


def git(root: Path, args: list[str], *, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "git failed")
    return result.stdout if binary else result.stdout.decode().strip()


def current_subject(root: Path) -> str:
    root = root.resolve()
    try:
        inside = git(root, ["rev-parse", "--is-inside-work-tree"]) == "true"
    except RuntimeError:
        inside = False
    if not inside:
        paths = [path for path in root.rglob("*") if (path.is_file() or path.is_symlink()) and not ignored(path.relative_to(root).as_posix())]
        entries = [entry(root, path.relative_to(root).as_posix()) for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix().encode("utf-8"))]
        descriptor = {"descriptorVersion": "0.1", "commitOid": None, "treeOid": None, "workspacePatchSha256": digest({"entries": entries})}
        return digest(descriptor)
    try:
        commit = str(git(root, ["rev-parse", "HEAD"]))
        tree = str(git(root, ["rev-parse", "HEAD^{tree}"]))
        patch = git(root, ["diff", "--binary", "--no-ext-diff", "HEAD", "--", ".", ":(exclude).proofed/**", ":(exclude)**/__pycache__/**", ":(exclude).pytest_cache/**", ":(exclude)node_modules/**"], binary=True)
    except RuntimeError:
        commit, tree, patch = None, None, b""
    raw = git(root, ["ls-files", "--others", "--exclude-standard", "-z"], binary=True)
    names = [item.decode("utf-8") for item in raw.split(b"\0") if item and not ignored(item.decode("utf-8"))]
    untracked = [entry(root, name) for name in sorted(names, key=lambda item: item.encode("utf-8"))]
    patch_descriptor = {"trackedPatchSha256": hashlib.sha256(patch).hexdigest(), "untracked": untracked}
    descriptor = {"descriptorVersion": "0.1", "commitOid": commit, "treeOid": tree, "workspacePatchSha256": digest(patch_descriptor)}
    return digest(descriptor)


def verify(bundle: Any, expected_subject: str | None = None, require_trust: str | None = None) -> list[str]:
    if not isinstance(bundle, dict) or bundle.get("bundleVersion") != "0.1":
        return ["UNSUPPORTED_BUNDLE_VERSION"]
    statements = bundle.get("statements")
    if not isinstance(statements, list):
        return ["MISSING_STATEMENTS"]
    completions = [item for item in statements if isinstance(item, dict) and item.get("predicateType") == COMPLETION_TYPE]
    tests = [item for item in statements if isinstance(item, dict) and item.get("predicateType") == TEST_RESULT_TYPE]
    if len(completions) != 1:
        return ["EXPECTED_ONE_COMPLETION_STATEMENT"]
    completion = completions[0]
    errors: list[str] = []
    if completion.get("_type") != STATEMENT_TYPE:
        errors.append("INVALID_STATEMENT_TYPE")
    subjects = completion.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        return errors + ["INVALID_SUBJECT"]
    subject_digest = subjects[0].get("digest", {}).get("sha256")
    if not isinstance(subject_digest, str) or len(subject_digest) != 64:
        errors.append("INVALID_SUBJECT_DIGEST")
    if expected_subject and subject_digest != expected_subject.removeprefix("sha256:"):
        errors.append("STALE_SUBJECT")
    predicate = completion.get("predicate")
    if not isinstance(predicate, dict) or predicate.get("schemaVersion") != "0.1":
        return sorted(set(errors + ["INVALID_COMPLETION_PREDICATE"]))
    descriptor = predicate.get("subjectDescriptor")
    if not isinstance(descriptor, dict) or digest(descriptor) != subject_digest:
        errors.append("SUBJECT_DESCRIPTOR_MISMATCH")
    trust = predicate.get("producer", {}).get("trustLevel")
    ranks = {"L0": 0, "L1": 1, "L2": 2}
    if trust not in ranks:
        errors.append("INVALID_TRUST_LEVEL")
    if require_trust in {"L1", "L2"}:
        errors.append("UNVERIFIED_TRUST_CLAIM")
    required = predicate.get("requiredEvidence")
    missing = predicate.get("missingEvidence")
    if not isinstance(required, list) or not isinstance(missing, list):
        errors.append("INVALID_EVIDENCE_LISTS")
        required, missing = [], []
    if predicate.get("decision") != "PASSED":
        errors.append("COMPLETION_NOT_PASSED")
    if (predicate.get("decision") == "PASSED") != (predicate.get("phase") == "PASSED"):
        errors.append("DECISION_PHASE_MISMATCH")
    if missing:
        errors.append("MISSING_REQUIRED_EVIDENCE")
    test_map = {digest(item): item for item in tests}
    referenced: list[dict[str, Any]] = []
    refs = predicate.get("evidenceRefs", [])
    if not isinstance(refs, list):
        errors.append("INVALID_EVIDENCE_REFS")
        refs = []
    for ref in refs:
        if isinstance(ref, dict) and ref.get("predicateType") == TEST_RESULT_TYPE:
            target = str(ref.get("digest", "")).removeprefix("sha256:")
            if target not in test_map:
                errors.append("BROKEN_EVIDENCE_REFERENCE")
            else:
                referenced.append(test_map[target])
    if "tests_passed" in required:
        if not referenced:
            errors.append("MISSING_TEST_RESULT")
        for statement in referenced:
            test_predicate = statement.get("predicate", {})
            if statement.get("_type") != STATEMENT_TYPE:
                errors.append("INVALID_TEST_STATEMENT_TYPE")
            if statement.get("subject") != completion.get("subject"):
                errors.append("TEST_SUBJECT_MISMATCH")
            if test_predicate.get("result") != "PASSED" or test_predicate.get("failedTests"):
                errors.append("TEST_RESULT_NOT_PASSED")
            configurations = test_predicate.get("configuration")
            if not isinstance(configurations, list) or not configurations:
                errors.append("MISSING_TEST_CONFIGURATION")
                configurations = []
            actual = [item.get("digest", {}).get("sha256") for item in configurations if isinstance(item, dict)]
            expected = predicate.get("policy", {}).get("testConfigurationDigests", [])
            if sorted(actual) != sorted(expected):
                errors.append("TEST_CONFIGURATION_MISMATCH")
    if "git_diff_recorded" in required and (not isinstance(descriptor, dict) or not descriptor.get("workspacePatchSha256")):
        errors.append("MISSING_GIT_DIFF_EVIDENCE")
    if set(required) - {"tests_passed", "git_diff_recorded"}:
        errors.append("UNKNOWN_REQUIRED_EVIDENCE")
    effects = predicate.get("effects", [])
    if not isinstance(effects, list):
        errors.append("INVALID_EFFECTS")
    else:
        for effect in effects:
            if isinstance(effect, dict) and effect.get("state") == "EFFECT_UNKNOWN" and effect.get("retryAllowed") is True:
                errors.append("UNKNOWN_EFFECT_RETRY_ALLOWED")
    policy = predicate.get("policy", {})
    if isinstance(policy, dict) and policy.get("evidenceDegradedByUser") is True and not policy.get("degradationAuthorization"):
        errors.append("UNAUTHORIZED_EVIDENCE_DEGRADATION")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Proofed SRR without the Proofed kernel")
    parser.add_argument("input")
    parser.add_argument("--current", metavar="PROJECT")
    parser.add_argument("--subject")
    parser.add_argument("--require-trust", choices=["L0", "L1", "L2"])
    parser.add_argument("--vectors", action="store_true")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.vectors:
        failures = []
        for case in data.get("cases", []):
            actual = verify(case["bundle"])
            expected = sorted(case["expectedErrors"])
            if actual != expected:
                failures.append({"name": case["name"], "expected": expected, "actual": actual})
        if failures:
            print(json.dumps(failures, indent=2))
            return 1
        print(f"PASS: {len(data.get('cases', []))} conformance vectors")
        return 0
    expected = args.subject
    if args.current:
        expected = current_subject(Path(args.current))
    errors = verify(data, expected, args.require_trust)
    if errors:
        print("INVALID: " + ", ".join(errors), file=sys.stderr)
        return 4
    print("VALID: completion receipt passed independent checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
