---
name: proofed-verify
description: Require current-subject evidence before claiming a coding task is complete.
---

# Proofed verification gate

Use this skill when a repository contains `.proofed.yml` and a coding task may
be completed.

1. Run `proofed status` before choosing the next action.
2. Do not repeat any failed path listed by status without new distinguishing evidence.
3. Before claiming completion, run `proofed verify`.
4. If evidence is missing, perform the printed next action. Tests are executed
   only with the explicit `proofed verify --run-tests` command.
5. Claim completion only when the receipt for the current repository subject is
   `PASSED`.
6. Never treat a host hook as unbypassable or a signature as proof of correctness.

