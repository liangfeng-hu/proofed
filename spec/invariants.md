# Proofed normative invariants

| ID | Invariant | v0.1 behavior |
|---|---|---|
| INV-001 | One active intent revision | reducer rejects parallel canonical promotion |
| INV-002 | Required evidence must precede PASSED | implemented and publicly demonstrated |
| INV-003 | Failed paths survive recovery | schema/state retained; full path capture is later work |
| INV-004 | `EFFECT_UNKNOWN` is never blindly retryable | verifier rejects `retryAllowed: true`; dispatch wrapper is not yet implemented |
| INV-005 | Candidate events cannot self-promote | only the reducer materializes canonical state |
| INV-006 | One public deterministic writer | SQLite materialization must equal event replay |

Only INV-002 is claimed as a complete v0.1 execution demo. INV-004 has protocol
validation but not pre-dispatch effect control. No invariant can be disabled by
an adapter or private module.

