from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_NAME = ".proofed.yml"
DEFAULT_REQUIRED = ["tests_passed", "git_diff_recorded"]


class ConfigError(ValueError):
    pass


def config_path(root: Path) -> Path:
    return root / CONFIG_NAME


def load_config(root: Path) -> dict[str, Any]:
    path = config_path(root)
    if not path.is_file():
        raise ConfigError("repository is not opted in; run: proofed init")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{CONFIG_NAME} must be valid JSON-compatible YAML: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ConfigError(f"{CONFIG_NAME} requires version: 1")
    tests = data.get("tests", {})
    completion = data.get("completion", {})
    hooks = data.get("hooks", {})
    if not isinstance(tests, dict) or not isinstance(completion, dict) or not isinstance(hooks, dict):
        raise ConfigError("tests, completion, and hooks must be objects")
    commands = tests.get("commands", [])
    required = completion.get("require", DEFAULT_REQUIRED)
    if not isinstance(commands, list) or not all(isinstance(x, list) for x in commands):
        raise ConfigError("tests.commands must be a list of argv lists")
    if not all(x and all(isinstance(part, str) and part for part in x) for x in commands):
        raise ConfigError("every test command must contain non-empty string argv entries")
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
        raise ConfigError("completion.require must be a list of strings")
    unknown = set(required) - {"tests_passed", "git_diff_recorded"}
    if unknown:
        raise ConfigError(f"unsupported required evidence: {', '.join(sorted(unknown))}")
    timeout = tests.get("timeout_seconds", 900)
    if not isinstance(timeout, int) or not 1 <= timeout <= 7200:
        raise ConfigError("tests.timeout_seconds must be an integer from 1 to 7200")
    return data


def write_config(root: Path, commands: list[list[str]], *, force: bool = False) -> Path:
    path = config_path(root)
    if path.exists() and not force:
        raise ConfigError(f"{CONFIG_NAME} already exists; use --force to replace it")
    data = {
        "version": 1,
        "tests": {
            "auto_inferred": True,
            "commands": commands,
            "timeout_seconds": 900,
        },
        "completion": {"require": list(DEFAULT_REQUIRED)},
        "hooks": {"stop_gate": True, "max_blocks_per_revision": 2},
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def find_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return current

