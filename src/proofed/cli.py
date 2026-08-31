from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .config import ConfigError, config_path, find_root, load_config, write_config


EXIT_REJECT = 2
EXIT_HOLD = 3
EXIT_INVALID = 4


def _root(value: str | None = None) -> Path:
    return find_root(Path(value or os.getcwd()))


def _project_id(root: Path) -> str:
    path = root / ".proofed" / "project-id"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = f"urn:uuid:{uuid.uuid4()}"
    path.write_text(value + "\n", encoding="utf-8")
    return value


def _print_state(state: dict[str, Any], *, context: bool = False) -> None:
    payload = {
        "intent": state["intent"],
        "intentRevision": state["intentRevision"],
        "phase": state["phase"],
        "next": state["nextLegalAction"],
        "missingEvidence": state["missingEvidence"],
        "failedPathsNotToRepeat": state["failedPathRefs"],
    }
    if context:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return
    print(f"Intent: {payload['intent']}")
    print(f"Phase: {payload['phase']}")
    missing = ", ".join(payload["missingEvidence"]) or "none"
    print(f"Missing evidence: {missing}")
    print(f"Next: {payload['next']}")
    if payload["failedPathsNotToRepeat"]:
        print("Do not repeat unchanged: " + ", ".join(payload["failedPathsNotToRepeat"]))


def _merge_claude_hooks(root: Path) -> Path:
    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"cannot merge invalid {settings_path}: {exc}") from exc
    else:
        settings = {}
    hooks = settings.setdefault("hooks", {})
    desired = {
        "SessionStart": {
            "matcher": "startup|resume|clear|compact|fork",
            "hooks": [{"type": "command", "command": "proofed hook-session-start"}],
        },
        "Stop": {
            "hooks": [{"type": "command", "command": "proofed hook-stop"}],
        },
    }
    for event, group in desired.items():
        groups = hooks.setdefault(event, [])
        marker = group["hooks"][0]["command"]
        present = any(
            handler.get("command") == marker
            for existing in groups
            if isinstance(existing, dict)
            for handler in existing.get("hooks", [])
            if isinstance(handler, dict)
        )
        if not present:
            groups.append(group)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return settings_path


def cmd_init(args: argparse.Namespace) -> int:
    from .evidence import infer_test_commands

    root = Path(args.target).resolve()
    existing = config_path(root).is_file()
    if existing and args.claude and not args.force:
        config = load_config(root)
        commands = config["tests"].get("commands", [])
        print(f"Kept existing {config_path(root)}")
    else:
        commands = infer_test_commands(root)
        path = write_config(root, commands, force=args.force)
        print(f"Created {path}")
        if commands:
            print(f"Detected {len(commands)} canonical test command(s).")
        else:
            print("HOLD: no canonical test command detected; edit .proofed.yml before verification.")
    if args.claude:
        if not args.accept_hooks:
            print("Hook not installed. Re-run with --claude --accept-hooks after reviewing the project hook command.")
            return EXIT_HOLD
        hook_path = _merge_claude_hooks(root)
        print(f"Installed project-scoped Claude hooks in {hook_path}")
        print("Review them in Claude Code with /hooks; workspace trust is controlled by Claude Code.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .kernel import Kernel

    root = _root(args.target)
    config = load_config(root)
    state = Kernel(root).start_run(
        project_id=_project_id(root),
        intent=args.intent,
        required_evidence=config["completion"].get("require", []),
        test_commands=config["tests"].get("commands", []),
    )
    print(f"Run active: {state['runId']}")
    _print_state(state)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .kernel import Kernel

    root = _root(args.target)
    load_config(root)
    state = Kernel(root).active_run()
    if state is None:
        if args.context:
            print('{"activeRun":false}')
        else:
            print("No active Proofed run.")
        return 0
    _print_state(state, context=args.context)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from .evidence import build_test_statement, run_tests
    from .kernel import Kernel
    from .receipt import build_bundle, build_completion_statement, write_bundle
    from .subject import current_subject

    root = _root(args.target)
    config = load_config(root)
    kernel = Kernel(root)
    state = kernel.active_run()
    if state is None:
        print("HOLD: no active run; run: proofed run .", file=sys.stderr)
        return EXIT_HOLD
    subject = current_subject(root)
    digest = subject["digest"]["sha256"]
    state = kernel.append(state["runId"], "VERIFICATION_REQUESTED", {"subjectDigest": digest})

    test_result = state["testEvidence"].get(digest)
    if args.run_tests:
        result = run_tests(
            root,
            state["testCommands"],
            config["tests"].get("timeout_seconds", 900),
        )
        subject = result.get("subject", subject)
        digest = subject["digest"]["sha256"]
        evidence = {
            "passed": bool(result.get("passed")),
            "reason": result.get("reason"),
            "runs": result.get("runs", []),
        }
        state = kernel.append(
            state["runId"],
            "TEST_EVIDENCE_RECORDED",
            {"subjectDigest": digest, "evidence": evidence},
        )
        test_result = evidence

    available = {"git_diff_recorded"}
    if test_result and test_result.get("passed"):
        available.add("tests_passed")
    missing = [item for item in state["requiredEvidence"] if item not in available]

    if args.ci and os.environ.get("GITHUB_ACTIONS") != "true":
        print("HOLD: --ci is only accepted inside GitHub Actions.", file=sys.stderr)
        return EXIT_HOLD
    trust = "L1" if args.ci else "L0"
    environment = "github-actions" if args.ci else "local"
    test_statement = build_test_statement(subject, test_result) if test_result else None

    if not state["testCommands"] and "tests_passed" in state["requiredEvidence"]:
        decision, code = "HOLD", "NO_TEST_COMMAND"
        message = "no canonical test command configured"
        next_action = "configure tests.commands in .proofed.yml"
    elif test_result and not test_result.get("passed"):
        decision, code = "REJECT", test_result.get("reason") or "TESTS_FAILED"
        message = "canonical tests did not pass"
        next_action = "inspect local .proofed/logs and fix the failing tests"
    elif missing:
        decision, code = "REJECT", "MISSING_REQUIRED_EVIDENCE"
        message = "missing " + ", ".join(missing)
        next_action = "run: proofed verify --run-tests"
    else:
        decision, code = "PASSED", "ALL_REQUIRED_EVIDENCE_PRESENT"
        message = "all required evidence matches the current subject"
        next_action = "none"

    completion = build_completion_statement(
        subject=subject,
        run_state=state,
        decision=decision,
        reason_code=code,
        reason_message=message,
        next_action=next_action,
        missing=missing,
        test_statement=test_statement,
        trust_level=trust,
        producer_environment=environment,
    )
    bundle = build_bundle(completion, test_statement)
    receipt_path = root / ".proofed" / "receipts" / f"completion-{state['runId']}-r{state['intentRevision']}.json"
    write_bundle(receipt_path, bundle)
    state = kernel.append(
        state["runId"],
        "VERIFICATION_DECIDED",
        {
            "decision": decision,
            "reason": {"code": code, "message": message},
            "missingEvidence": missing,
            "nextLegalAction": next_action,
            "subjectDigest": digest,
            "receiptPath": str(receipt_path.relative_to(root)),
        },
    )
    if decision == "PASSED":
        print("PASSED: current code has all required evidence")
        print(f"Receipt: {state['receiptPath']}")
        print(f"Subject: sha256:{digest}")
        return 0
    print(f"{decision}: {message}", file=sys.stderr)
    print(f"Next: {next_action}", file=sys.stderr)
    print(f"Receipt: {state['receiptPath']}", file=sys.stderr)
    return EXIT_HOLD if decision == "HOLD" else EXIT_REJECT


def cmd_check_receipt(args: argparse.Namespace) -> int:
    from .receipt import verify_bundle

    try:
        bundle = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_INVALID
    expected = None
    if args.current:
        from .subject import current_subject

        expected = current_subject(_root(args.current))["digest"]["sha256"]
    errors = verify_bundle(bundle, expected_subject=expected, require_trust=args.require_trust)
    if errors:
        print("INVALID: " + ", ".join(errors), file=sys.stderr)
        return EXIT_INVALID
    print("VALID: completion receipt passed independent checks")
    return 0


def _read_hook_input() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _hook_root(payload: dict[str, Any]) -> Path:
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return _root(str(cwd))


def cmd_hook_session_start(_args: argparse.Namespace) -> int:
    payload = _read_hook_input()
    root = _hook_root(payload)
    if not config_path(root).is_file() or not (root / ".proofed" / "state.db").is_file():
        return 0
    from .kernel import Kernel

    kernel = Kernel(root)
    state = kernel.active_run()
    if state is None:
        return 0
    state = kernel.append(
        state["runId"],
        "HOOK_HANDSHAKE",
        {"host": "claude-code", "event": "SessionStart", "source": payload.get("source")},
    )
    context = {
        "intent": state["intent"],
        "intentRevision": state["intentRevision"],
        "phase": state["phase"],
        "missingEvidence": state["missingEvidence"],
        "next": state["nextLegalAction"],
        "failedPathsNotToRepeat": state["failedPathRefs"],
    }
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Proofed: " + json.dumps(context, ensure_ascii=False)}}))
    return 0


def cmd_hook_stop(_args: argparse.Namespace) -> int:
    payload = _read_hook_input()
    root = _hook_root(payload)
    if not config_path(root).is_file() or not (root / ".proofed" / "state.db").is_file():
        return 0
    from .kernel import Kernel
    from .subject import current_subject

    config = load_config(root)
    if not config.get("hooks", {}).get("stop_gate", False):
        return 0
    kernel = Kernel(root)
    state = kernel.active_run()
    if state is None:
        return 0
    state = kernel.append(
        state["runId"],
        "HOOK_HANDSHAKE",
        {"host": "claude-code", "event": "Stop", "source": None},
    )
    if payload.get("background_tasks"):
        return 0
    if payload.get("stop_hook_active") is True:
        kernel.append(
            state["runId"],
            "HOLD_RECORDED",
            {"reason": {"code": "HOST_STOP_REENTRY", "message": "host stop hook re-entry"}, "nextLegalAction": "review Proofed status manually"},
        )
        return 0
    if state["phase"] != "VERIFYING" and not state["completionRequested"]:
        return 0
    subject = current_subject(root)["digest"]["sha256"]
    if state.get("decision") == "PASSED" and state.get("subjectDigest") == subject:
        return 0
    reason = (state.get("reason") or {}).get("code") or "MISSING_REQUIRED_EVIDENCE"
    budget_key = "|".join(["claude-code", state["runId"], str(state["intentRevision"]), subject, reason])
    count = int(state.get("hookBlocks", {}).get(budget_key, 0))
    maximum = int(config.get("hooks", {}).get("max_blocks_per_revision", 2))
    if count >= maximum:
        kernel.append(
            state["runId"],
            "HOLD_RECORDED",
            {"reason": {"code": "BLOCK_BUDGET_EXHAUSTED", "message": "automatic stop block budget exhausted"}, "nextLegalAction": "run proofed status and resolve or cancel the run"},
        )
        return 0
    kernel.append(state["runId"], "HOOK_BLOCKED", {"budgetKey": budget_key})
    missing = ", ".join(state.get("missingEvidence", [])) or "current subject evidence"
    print(json.dumps({"decision": "block", "reason": f"Proofed rejected completion: missing {missing}. Next: {state['nextLegalAction']}"}, ensure_ascii=False))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = _root(args.target)
    opted_in = config_path(root).is_file()
    settings = root / ".claude" / "settings.json"
    configured = settings.is_file() and "proofed hook-stop" in settings.read_text(encoding="utf-8", errors="ignore")
    handshake = None
    active = False
    if (root / ".proofed" / "state.db").is_file():
        from .kernel import Kernel

        state = Kernel(root).active_run()
        if state:
            active = True
            handshake = state.get("lastHookHandshake")
    print(f"Repository opt-in: {'yes' if opted_in else 'no'}")
    print(f"Active run: {'yes' if active else 'no'}")
    print(f"Claude project hook configured: {'yes' if configured else 'no'}")
    print(f"Recent hook handshake: {'yes' if handshake else 'no'}")
    print("Claude workspace trust: unknown (review with /hooks in Claude Code)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofed")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create repository opt-in configuration")
    init.add_argument("target", nargs="?", default=".")
    init.add_argument("--force", action="store_true")
    init.add_argument("--claude", action="store_true", help="also install project-scoped Claude Code hooks")
    init.add_argument("--accept-hooks", action="store_true", help="confirm review of the hook command")
    init.set_defaults(func=cmd_init)

    run = sub.add_parser("run", help="start or resume a user-owned completion run")
    run.add_argument("target", nargs="?", default=".")
    run.add_argument("--intent", default="complete the current repository task")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show the next legal action and missing evidence")
    status.add_argument("target", nargs="?", default=".")
    status.add_argument("--context", action="store_true")
    status.set_defaults(func=cmd_status)

    verify = sub.add_parser("verify", help="verify required evidence for the current subject")
    verify.add_argument("target", nargs="?", default=".")
    verify.add_argument("--run-tests", action="store_true")
    verify.add_argument("--ci", action="store_true", help=argparse.SUPPRESS)
    verify.set_defaults(func=cmd_verify)

    check = sub.add_parser("check-receipt", help="verify a receipt without opening the Proofed state database")
    check.add_argument("receipt")
    check.add_argument("--current", metavar="PROJECT")
    check.add_argument("--require-trust", choices=["L0", "L1", "L2"])
    check.set_defaults(func=cmd_check_receipt)

    doctor = sub.add_parser("doctor", help="diagnose opt-in and hook visibility without changing trust")
    doctor.add_argument("target", nargs="?", default=".")
    doctor.set_defaults(func=cmd_doctor)

    session = sub.add_parser("hook-session-start", help=argparse.SUPPRESS)
    session.set_defaults(func=cmd_hook_session_start)
    stop = sub.add_parser("hook-stop", help=argparse.SUPPRESS)
    stop.set_defaults(func=cmd_hook_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return EXIT_HOLD
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
