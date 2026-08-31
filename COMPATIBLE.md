# Compatible implementations

## Independent external implementations

No independent external implementation has been verified yet.

An entry is added here only when a non-maintainer producer, verifier, consumer,
or host adapter passes the shared conformance vectors without importing the
Proofed kernel. Self-authored adapters do not count as protocol adoption.

## Cross-repository owner pilots

The following public repositories run the released
`liangfeng-hu/proofed@v0.1.0-alpha.2` Action against their own current
checkout. They demonstrate cross-repository integration, but do not count as
independent external adoption.

| Repository | Canonical verification | Merged integration | Main-branch run |
| --- | --- | --- | --- |
| [openclaw-flight-recorder](https://github.com/liangfeng-hu/openclaw-flight-recorder) | Python unittest discovery | [PR #1](https://github.com/liangfeng-hu/openclaw-flight-recorder/pull/1) | [PASS](https://github.com/liangfeng-hu/openclaw-flight-recorder/actions/runs/33384079257) |
| [yfcore-pcc-lite-verifier](https://github.com/liangfeng-hu/yfcore-pcc-lite-verifier) | Deterministic acceptance vectors | [PR #1](https://github.com/liangfeng-hu/yfcore-pcc-lite-verifier/pull/1) | [PASS](https://github.com/liangfeng-hu/yfcore-pcc-lite-verifier/actions/runs/33384093022) |
| [Cosmic-Seed-DistillGuard-Reference](https://github.com/liangfeng-hu/Cosmic-Seed-DistillGuard-Reference) | Demo assertions and fail-closed markers | [PR #1](https://github.com/liangfeng-hu/Cosmic-Seed-DistillGuard-Reference/pull/1) | [PASS](https://github.com/liangfeng-hu/Cosmic-Seed-DistillGuard-Reference/actions/runs/33384109644) |

These pilots establish that the public Action can execute outside its source
repository with three distinct project verification shapes. Required-check
enforcement and non-maintainer adoption are tracked separately.
