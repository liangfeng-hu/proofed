from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import TEST_RESULT_TYPE
from .subject import canonical_json, sha256_bytes


STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
COMPLETION_TYPE = "urn:uuid:7ec9a0e8-9d21-4b8c-9bdd-11e1ab3c87cf"
ALLOWED_TRUST = {"L0", "L1", "L2"}


def statement_digest(statement: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(statement))


def build_completion_statement(
    *,
    subject: dict[str, Any],
    run_state: dict[str, Any],
    decision: str,
    reason_code: str,
    reason_message: str,
    next_action: str,
    missing: list[str],
    test_statement: dict[str, Any] | None,
    trust_level: str,
    producer_environment: str,
) -> dict[str, Any]:
    refs = []
    if test_statement is not None:
        refs.append(
            {
                "predicateType": TEST_RESULT_TYPE,
                "digest": f"sha256:{statement_digest(test_statement)}",
            }
        )
    commands = run_state.get("testCommands", [])
    from .evidence import command_digests

    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": subject["name"], "digest": subject["digest"]}],
        "predicateType": COMPLETION_TYPE,
        "predicate": {
            "schemaVersion": "0.1",
            "runId": run_state["runId"],
            "projectId": run_state["projectId"],
            "intentRevision": run_state["intentRevision"],
            "phase": "PASSED" if decision == "PASSED" else "VERIFYING",
            "decision": decision,
            "reason": {"code": reason_code, "message": reason_message},
            "nextLegalAction": next_action,
            "requiredEvidence": run_state["requiredEvidence"],
            "missingEvidence": missing,
            "evidenceRefs": refs,
            "failedPathRefs": list(run_state.get("failedPathRefs", [])),
            "effects": list(run_state.get("effects", [])),
            "subjectDescriptor": subject["descriptor"],
            "policy": {
                "evidenceDegradedByUser": False,
                "testConfigurationDigests": command_digests(commands),
            },
            "producer": {
                "name": "proofed",
                "version": "0.1.0-alpha.1",
                "trustLevel": trust_level,
                "environment": producer_environment,
            },
        },
    }


def build_bundle(completion: dict[str, Any], test_statement: dict[str, Any] | None) -> dict[str, Any]:
    statements = [completion]
    if test_statement is not None:
        statements.append(test_statement)
    return {"bundleVersion": "0.1", "statements": statements}


def verify_bundle(
    bundle: dict[str, Any],
    *,
    expected_subject: str | None = None,
    require_trust: str | None = None,
) -> list[str]:
    errors: list[str] = []
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
    if completion.get("_type") != STATEMENT_TYPE:
        errors.append("INVALID_STATEMENT_TYPE")
    subjects = completion.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        errors.append("INVALID_SUBJECT")
        return errors
    digest = subjects[0].get("digest", {}).get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        errors.append("INVALID_SUBJECT_DIGEST")
    if expected_subject and digest != expected_subject.removeprefix("sha256:"):
        errors.append("STALE_SUBJECT")
    predicate = completion.get("predicate")
    if not isinstance(predicate, dict) or predicate.get("schemaVersion") != "0.1":
        errors.append("INVALID_COMPLETION_PREDICATE")
        return errors
    descriptor = predicate.get("subjectDescriptor")
    if not isinstance(descriptor, dict) or sha256_bytes(canonical_json(descriptor)) != digest:
        errors.append("SUBJECT_DESCRIPTOR_MISMATCH")
    producer = predicate.get("producer", {})
    trust = producer.get("trustLevel") if isinstance(producer, dict) else None
    if trust not in ALLOWED_TRUST:
        errors.append("INVALID_TRUST_LEVEL")
    if require_trust in {"L1", "L2"}:
        # A naked JSON field cannot prove CI or signer identity. v0.1 deliberately
        # has no offline L1/L2 acceptance path until an external attestation is checked.
        errors.append("UNVERIFIED_TRUST_CLAIM")
    required = predicate.get("requiredEvidence")
    missing = predicate.get("missingEvidence")
    if not isinstance(required, list) or not isinstance(missing, list):
        errors.append("INVALID_EVIDENCE_LISTS")
        required = []
        missing = []
    if predicate.get("decision") != "PASSED":
        errors.append("COMPLETION_NOT_PASSED")
    if (predicate.get("decision") == "PASSED") != (predicate.get("phase") == "PASSED"):
        errors.append("DECISION_PHASE_MISMATCH")
    if missing:
        errors.append("MISSING_REQUIRED_EVIDENCE")
    refs = predicate.get("evidenceRefs", [])
    if not isinstance(refs, list):
        errors.append("INVALID_EVIDENCE_REFS")
        refs = []
    test_by_digest = {statement_digest(item): item for item in tests}
    referenced_tests: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("predicateType") != TEST_RESULT_TYPE:
            continue
        raw = ref.get("digest", "")
        target = raw.removeprefix("sha256:") if isinstance(raw, str) else ""
        if target not in test_by_digest:
            errors.append("BROKEN_EVIDENCE_REFERENCE")
        else:
            referenced_tests.append(test_by_digest[target])
    if "tests_passed" in required:
        if not referenced_tests:
            errors.append("MISSING_TEST_RESULT")
        for statement in referenced_tests:
            test_predicate = statement.get("predicate", {})
            if statement.get("_type") != STATEMENT_TYPE:
                errors.append("INVALID_TEST_STATEMENT_TYPE")
            if statement.get("subject") != completion.get("subject"):
                errors.append("TEST_SUBJECT_MISMATCH")
            if test_predicate.get("result") != "PASSED" or test_predicate.get("failedTests"):
                errors.append("TEST_RESULT_NOT_PASSED")
            configuration = test_predicate.get("configuration")
            if not isinstance(configuration, list) or not configuration:
                errors.append("MISSING_TEST_CONFIGURATION")
            expected_configs = predicate.get("policy", {}).get("testConfigurationDigests", [])
            actual_configs = [item.get("digest", {}).get("sha256") for item in configuration if isinstance(item, dict)]
            if sorted(expected_configs) != sorted(actual_configs):
                errors.append("TEST_CONFIGURATION_MISMATCH")
    if "git_diff_recorded" in required:
        if not isinstance(descriptor, dict) or not descriptor.get("workspacePatchSha256"):
            errors.append("MISSING_GIT_DIFF_EVIDENCE")
    unknown_required = set(required) - {"tests_passed", "git_diff_recorded"}
    if unknown_required:
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


def write_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
