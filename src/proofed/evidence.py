from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .subject import canonical_json, current_subject, sha256_bytes


TEST_RESULT_TYPE = "https://in-toto.io/attestation/test-result/v0.1"


def infer_test_commands(root: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    python_test_files = list((root / "tests").glob("test_*.py"))
    has_python_tests = (root / "pytest.ini").is_file() or bool(python_test_files)
    pyproject = root / "pyproject.toml"
    mentions_pytest = pyproject.is_file() and "pytest" in pyproject.read_text(
        encoding="utf-8", errors="ignore"
    ).lower()
    mentions_unittest = any(
        "unittest" in path.read_text(encoding="utf-8", errors="ignore")
        for path in python_test_files
    )
    if has_python_tests or mentions_pytest:
        if importlib.util.find_spec("pytest") is not None or mentions_pytest:
            commands.append([sys.executable, "-m", "pytest", "-q"])
        elif mentions_unittest:
            commands.append([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            script = package.get("scripts", {}).get("test")
            placeholder = "no test specified" in str(script).lower()
            if script and not placeholder:
                commands.append(["npm", "test"])
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return commands


def _configuration_descriptor(argv: list[str]) -> dict[str, Any]:
    command_spec = {"argv": argv, "version": "0.1"}
    return {
        "name": "canonical-test-command",
        "digest": {"sha256": sha256_bytes(canonical_json(command_spec))},
    }


def command_digests(commands: list[list[str]]) -> list[str]:
    return [_configuration_descriptor(command)["digest"]["sha256"] for command in commands]


def run_tests(root: Path, commands: list[list[str]], timeout_seconds: int) -> dict[str, Any]:
    if not commands:
        return {"passed": False, "reason": "NO_TEST_COMMAND", "runs": []}
    proofed_dir = root / ".proofed"
    logs_dir = proofed_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    before = current_subject(root)
    runs: list[dict[str, Any]] = []
    all_passed = True
    for index, argv in enumerate(commands, start=1):
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            output = completed.stdout
            exit_code = completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"") + (exc.stderr or b"")
            exit_code = 124
            timed_out = True
        duration_ms = int((time.monotonic() - started) * 1000)
        log_path = logs_dir / f"test-{index}.log"
        log_path.write_bytes(output)
        try:
            log_path.chmod(0o600)
        except OSError:
            pass
        run = {
            "configuration": _configuration_descriptor(argv),
            "exitCode": exit_code,
            "timedOut": timed_out,
            "durationMillis": duration_ms,
            "outputSha256": hashlib.sha256(output).hexdigest(),
        }
        runs.append(run)
        if exit_code != 0:
            all_passed = False
    after = current_subject(root)
    subject_stable = before["digest"] == after["digest"]
    return {
        "passed": all_passed and subject_stable,
        "reason": None if all_passed and subject_stable else (
            "SUBJECT_CHANGED_DURING_TESTS" if not subject_stable else "TESTS_FAILED"
        ),
        "subject": after,
        "subjectStable": subject_stable,
        "runs": runs,
    }


def build_test_statement(subject: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    configurations = [run["configuration"] for run in result.get("runs", [])]
    passed_names = [f"canonical-suite-{i}" for i, run in enumerate(result.get("runs", []), 1) if run["exitCode"] == 0]
    failed_names = [f"canonical-suite-{i}" for i, run in enumerate(result.get("runs", []), 1) if run["exitCode"] != 0]
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": subject["name"], "digest": subject["digest"]}],
        "predicateType": TEST_RESULT_TYPE,
        "predicate": {
            "result": "PASSED" if result.get("passed") else "FAILED",
            "configuration": configurations,
            "passedTests": passed_names,
            "warnedTests": [],
            "failedTests": failed_names,
        },
    }
