# Diagnostics and failure reports

The exercises answer two different questions. With the stack running, can the
operator narrow a failure to a particular route? After recovery, can the
operator still see what the candidate did before it was replaced?

## Evidence so far

| Exercise | Result on the dedicated demo |
|---|---|
| Healthy v1 at `80bd059` | Both smoke routes passed before and after diagnostics. The API resolved the database name and reached its TCP port. Both catalogue reads passed. All 225 tests passed in normal and optimized Python. |
| Wrong expected release at the Batch B change committed as `eb702f6` | Both suites passed all 238 tests. A verify-only operation failed and preserved the last successful v1. The driver checked that exporting by operation ID reproduced the same JSON. Both smoke routes passed afterwards. |
| PostgreSQL stopped | Name resolution failed. The TCP check skipped because it had no running database address. Direct and proxied catalogue reads returned HTTP 503. The separate outage smoke checks passed on both routes. |
| NGINX stopped | Database DNS, TCP and the direct catalogue read passed. Diagnostics skipped the exited proxy. After each dependency exercise the same containers were present, the journal snapshot was unchanged and all four routes passed. |
| Candidate exited before serving requests | The manual rollback restored v1 after the default deployment failed. In a separate opt-in deployment the failed candidate and the one successful automatic recovery appeared in the same report. The requested deployment returned exit 1. |

The owner ran 246 tests in normal and optimized Python with warnings treated
as errors. Both runs passed, and pip found no broken requirements. The failed
automatic deployment was `458b0f10d49c4a51b3795bb8cba8dc84`. Its recovery
was `b30ecc6853d44cf7a132cc2eabf04202`. Export by recovery ID returned the
candidate's report path with matching JSON. Final status recorded v1 as the
last success, and both smoke routes passed. These observations cover this
single-host run. The DNS result and probe timings can vary on another run.

A subsequent regression check removes the derived report in a temporary test
checkout before requesting it by recovery ID. This tests regeneration when
the report is missing. The standalone smoke checker also rejects HTTP redirects
and requires integer catalogue IDs.

The first sample of the release mismatch showed successful liveness and
catalogue reads through both routes. Both version responses had unexpected
content. On attempt 5, liveness still passed, the direct version worker
returned no usable result and the remaining three HTTP requests ran out of
time before starting. Final container inspection was unconfirmed. The report
preserves both samples because the final retry alone gives an incomplete
account of the failure.

## Run the exercises

Use the initialized demo with v1 already healthy and run from the repository
root. Keep other toolkit and Docker operations idle. Run one stage at a time.
The first two temporarily interrupt a dependency. The third replaces the API
and creates journal records, ignored reports and a local test image.

```bash
python scripts/phase4-acceptance.py database
python scripts/phase4-acceptance.py proxy
python scripts/phase4-acceptance.py candidate
```

| Stage | While the fault is present | Required end state |
|---|---|---|
| Database | Stop the owned database container by full ID. The TCP probe skips because there is no confirmed running database address. DNS and HTTP observations can vary with timing. The independent smoke test must observe HTTP 503 for readiness and catalogue on both routes, with liveness and version still available. | The same database container restarts. Preflight, both smoke routes and all four diagnostics pass. The latest operation and last success are preserved. |
| Proxy | Stop the owned NGINX container by full ID. The direct catalogue read, DNS and TCP checks must pass. The proxy probe is skipped because its container is stopped. | The same proxy restarts and both routes work again, with the original API instance and dependency IDs. |
| Candidate | Run the existing Phase 3 automatic stage with a newly built image that exits before serving HTTP. It also exercises refusal of a temporary Compose comment and the manual default before its opt-in run. Read the automatically generated JSON before requesting an export. | A newly failed deployment and its separately successful recovery appear in the same candidate report. The retained samples identify the candidate image. Export by recovery ID reproduces the JSON. The original v1 image passes both routes and all four diagnostics, with its original dependency IDs. |

The dependency stages hold the checkout lock and issue start in a `finally`
block. Power loss, a hard kill or an unavailable Docker daemon can interrupt
cleanup. If a stage stops, inspect `python -m toolkit status` and
`docker compose ps -a`. If only the exercised dependency is still exited,
confirm its ID against the one printed and start that exact container with
`docker --context default container start CONTAINER_ID`. Verify readiness and
run the smoke and diagnostic checks again. For pending deployment state, use
the repository's reconciliation procedure before another deployment.

The database and proxy stages check terminal diagnostics. Neither creates a
deployment failure record. The candidate stage checks persisted verification
observations. DNS and TCP samples from a later healthy stack cannot reconstruct
the failed candidate's network conditions.

A passing stage ends with its own PASS line. If a later run fails, keep the
output and record the affected stage and the final observed state.
