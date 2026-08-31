# False-completion red/green demo

This tiny repository has a real test. The first verification is rejected because
no test evidence exists for the current subject. The second explicitly runs the
canonical test command and passes.

From this directory, with Proofed installed:

```bash
git init
git add .
git -c user.name=demo -c user.email=demo@example.invalid commit -m baseline
proofed init
proofed run . --intent "verify integer addition"
proofed verify
proofed verify --run-tests
```

Then change `calculator.py` and run `proofed check-receipt RECEIPT --current .`.
The old PASS is rejected as `STALE_SUBJECT`.

