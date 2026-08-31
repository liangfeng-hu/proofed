# Proofed

[![Proofed CI](https://github.com/liangfeng-hu/proofed/actions/workflows/ci.yml/badge.svg)](https://github.com/liangfeng-hu/proofed/actions/workflows/ci.yml)

Coding agents can claim “done” without evidence. Proofed refuses `PASSED` until
the current code has the evidence your repository requires.

Agent Skills describe how to do work. Proofed defines when that work may be
called complete—and keeps the next step after a session interruption.

```bash
python -m pip install .
proofed init
proofed run .
proofed verify                 # REJECTED: missing tests_passed
proofed verify --run-tests     # PASSED after the configured tests pass
```

Inspect the durable next step:

```bash
proofed status
```

Verify a receipt without opening the Proofed state database:

```bash
proofed check-receipt .proofed/receipts/completion-*.json --current .
python verifiers/python/check_receipt.py RECEIPT --current .
node verifiers/javascript/check-receipt.mjs RECEIPT --current .
```

The included composite GitHub Action re-verifies the current checkout and runs
the configured tests. It never trusts an arbitrary unsigned `PASSED` file.

```yaml
- uses: liangfeng-hu/proofed@v0.1.0-alpha.1
  with:
    target: .
```

Repository opt-in is explicit through `.proofed.yml`. The first host adapter is
Claude Code; install it only after reviewing the command:

```bash
proofed init --claude --accept-hooks
proofed doctor
```

Proofed v0.1-alpha currently enforces evidence-gated completion and stale-subject
rejection. It does not provide production closure, universal exactly-once
effects, an unbypassable host hook, or proof that passing tests imply correct
software.

See `examples/false-completion`, `spec/srr-0.1.md`, and `spec/invariants.md`.
