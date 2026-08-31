# Skill Run Receipt (SRR) v0.1-alpha

## Identity

The canonical Proofed Completion predicate type is:

`urn:uuid:7ec9a0e8-9d21-4b8c-9bdd-11e1ab3c87cf`

This UUID-URN avoids claiming control of an unowned domain. A future resolvable
HTTPS alias may be published, but this v0.1 identifier will not be repurposed.

## Bundle

An SRR bundle is a JSON object with `bundleVersion: "0.1"` and a `statements`
array. It contains exactly one in-toto Statement v1 using the Completion
predicate and, when tests are claimed, an in-toto Test Result v0.1 Statement.

The completion statement binds one `repository-state` subject. Its `sha256` is
the digest of this canonical descriptor:

```json
{
  "descriptorVersion": "0.1",
  "commitOid": "<hex-or-null>",
  "treeOid": "<hex-or-null>",
  "workspacePatchSha256": "<sha256>"
}
```

The workspace patch descriptor includes a binary tracked diff digest and sorted
untracked path/content digests. `.git`, `.proofed`, dependency folders, and
well-known test caches are excluded. A code or configuration change therefore
invalidates the old subject while receipt/log creation does not.

The v0.1 canonicalization domain uses fixed ASCII schema keys, UTF-8 strings,
booleans, nulls, arrays, objects, and integers only. Sorted compact JSON is
RFC 8785-equivalent for this restricted domain; floats are forbidden.

## Evidence and trust

`evidenceRefs` carries `sha256:<digest>` references to canonical statements.
For `tests_passed`, the referenced Test Result must say `PASSED`, have no failed
tests, match the completion subject, and contain exactly the configuration
digests required by the completion policy.

- L0: unsigned local result; valid for local feedback, never sufficient merely
  because a committed file says PASS.
- L1: current checkout re-executed by the required CI job. The green required
  job is the trust fact; a detached JSON file merely claiming `L1` is not.
- L2: signed/attested result whose identity policy also verifies. Detached L2
  acceptance is unavailable until that verification path is implemented.

The included Action implements `verify-current` (L1 job behavior). It does not
implement signature-based `check-attestation` yet.

Receipts omit absolute paths, remote URLs, source, transcripts, and raw logs.
Independent verifiers need neither SQLite nor the Proofed kernel.
