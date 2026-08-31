# Security policy

Proofed is alpha software. Report suspected vulnerabilities through a private
GitHub security advisory in this repository. Do not disclose a vulnerability in
a public issue before the maintainer has had a reasonable opportunity to assess
it. Do not treat this package as a production security boundary.

Receipts intentionally exclude source code, repository remotes, absolute paths,
full test logs, and conversation transcripts. Test output remains under
`.proofed/logs/` and is not uploaded by the included Action.

The v0.1 threat model rejects missing evidence, stale receipts, broken evidence
references, unknown effects marked retryable, canonical-log corruption, and
infinite Stop-hook loops. It does not defend against a malicious repository
administrator, dishonest tests, a compromised CI identity, or a disabled hook.
