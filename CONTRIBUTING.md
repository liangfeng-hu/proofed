# Contributing

The fastest useful contributions are deliberately small:

1. one deterministic test collector with a fixture;
2. one sanitized false-completion case with a red/green expectation;
3. one documented host-hook field or trust difference with a vector.

Run `python -m unittest discover -s tests -v` and
`node verifiers/javascript/check-receipt.mjs spec/test-vectors/vectors.json --vectors`.

Changes to invariants, predicate fields, subject binding, or writer authority
require a design note, migration rule, cross-language vectors, and a negative
case. Private services may not enter the default verification path.

