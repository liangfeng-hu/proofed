---
name: proofed-verify
description: Use before a coding agent claims a repository task is done. Require current-code evidence, reject stale receipts, and preserve the next legal action after interruption.
---

# Proofed verification gate

Use this skill when a repository task is about to be called complete, or when a
user asks whether an agent's completion claim has current evidence.

1. Check for both the `proofed` command and repository opt-in `.proofed.yml`.
   If either is absent, say that the gate has not run. Do not imply verification.
2. Before modifying the environment, ask the user. After the PyPI release, use
   `python -m pip install proofed-agent`; until then, the pinned alpha install is
   `python -m pip install "git+https://github.com/liangfeng-hu/proofed.git@v0.1.0-alpha.1"`.
   Repository opt-in is `proofed init`.
3. Run `proofed status` before choosing the next action. Do not repeat a failed
   path listed there without new distinguishing evidence.
4. Before claiming completion, run `proofed verify`.
5. If it reports missing test evidence and the repository-configured command is
   appropriate, run `proofed verify --run-tests`; otherwise perform the printed
   next action explicitly.
6. Claim completion only when a `PASSED` receipt matches the current subject.
   Any later code change requires fresh evidence.
7. Never treat a host hook as unbypassable, a signed receipt as proof of
   correctness, or a missing configuration as permission to silently enforce.
