# Proofed

[![Proofed CI](https://github.com/liangfeng-hu/proofed/actions/workflows/ci.yml/badge.svg)](https://github.com/liangfeng-hu/proofed/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/liangfeng-hu/proofed?include_prereleases)](https://github.com/liangfeng-hu/proofed/releases) [![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

### Ask the code—not the agent—whether the work is done.

Coding agents can claim “done” without evidence. Proofed refuses `PASSED` until the **current code** has the test and diff evidence your repository requires, then writes a portable completion receipt. Agent Skills describe how to do the work; Proofed defines when it may be called complete—and preserves the next step after an interruption.

## See false completion rejected

```console
$ proofed verify
REJECT: missing tests_passed
Next: run: proofed verify --run-tests

$ proofed verify --run-tests
PASSED: current code has all required evidence
Receipt: .proofed/receipts/completion-...json
```

[Run the complete red/green demo](examples/false-completion) in about 30 seconds. Change the code afterward and the old receipt is rejected as `STALE_SUBJECT`.

## Start in an existing repository

```bash
python -m pip install "git+https://github.com/liangfeng-hu/proofed.git@v0.1.0-alpha.1"
proofed init
proofed run . --intent "finish the current repository task"
proofed status
proofed verify --run-tests
```

`proofed init` is the explicit repository opt-in. It currently detects canonical `pytest`, `unittest`, and `npm test` commands.

## Make it a required PR check

```yaml
- uses: liangfeng-hu/proofed@v0.1.0-alpha.1
  with:
    target: .
```

The Action re-runs configured tests against the current checkout; it does not trust a committed `PASSED` JSON file. See [`action.yml`](action.yml).

Verify a receipt without the kernel using the independent [Python](verifiers/python/check_receipt.py) or [JavaScript](verifiers/javascript/check-receipt.mjs) verifier. Both share conformance vectors; code changes invalidate old receipts.

## Go deeper

- [`spec/srr-0.1.md`](spec/srr-0.1.md) — receipt format, subject binding, and L0/L1/L2 trust model
- [`spec/invariants.md`](spec/invariants.md) — normative invariants and exact v0.1 coverage
- [`skills/proofed-verify/SKILL.md`](skills/proofed-verify/SKILL.md) — Agent Skill entry point
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — add a collector, false-completion case, or independent implementation

## Alpha boundary

Proofed v0.1-alpha enforces evidence-gated completion and stale-subject rejection. It does **not** claim production closure, universal exactly-once effects, an unbypassable host hook, or that passing tests proves correct software. The Claude Code hook is optional, project-scoped, and loop-budgeted; CI is the stronger enforcement surface.
