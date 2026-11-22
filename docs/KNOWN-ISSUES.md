# Known Issues and Limitations

The Phase 3 live exercises passed on the dedicated demo. They covered flagged
and strict manual rollback, controlled toolkit exits and one opt-in automatic
recovery after a failed deployment. Phase 4 covers diagnostics and failure reports. Phase 5 covers CI
evidence and release verification. [Phase 3 verification](PHASE-3-RECOVERY.md#combined-live-results)

Recovery evidence is specific to the checkout, comparison key, renderer and
observed dependencies. Replacing a healthy database or upgrading the Compose
plugin can invalidate older targets. A deleted key blocks attempts that depend
on it. The schema check covers the catalogue columns and primary key. Triggers,
data history and general application compatibility exceed that check. The
runtime observations cover the fields listed in the [recovery contract](PHASE-3-RECOVERY.md#batch-b-implementation).

## Phase 1 verification record (historical)

The following summarizes local terminal runs reviewed during Phase 1, including
the locked rebuild and fresh development-environment checks on 16 November 2026.
The reported environment was EndeavourOS x86_64, Python 3.14.10,
Docker Engine 29.9.3, and Compose 5.7.1. These are local results, not CI results or an independent audit.
The implementation was still on the unmerged Phase 1 branch when checked.

| Exercise | Observed result | Evidence boundary |
|---|---|---|
| Initial setup and repeated initialization | Fixture verification succeeded; normal smoke checks passed. | Does not validate arbitrary existing schemas or data. |
| Healthy HTTP paths | Four endpoints returned expected status codes and bodies directly and through NGINX. | Point-in-time checks only. |
| Database stop and restart | Liveness/version remained available; readiness/items returned generic HTTP 503; reads recovered without restarting the API. | Not a query-timeout, network-blackhole, or crash-recovery test. |
| API account permissions | SELECT succeeded; INSERT, UPDATE, and DELETE were rejected with SQLSTATE 42501 even in read-write transactions. | Tests targeted `public.items` with zero-row writes, not every database privilege. |
| Database-container replacement | Container ID changed, volume name stayed the same, and all three records survived without reseeding. | Does not cover deleted volumes, disk failure, or disaster recovery. |
| Conflicting fixture | Initialization function rejected a changed fixture and preserved it; the test restored and verified the original records. | Did not directly exercise the standalone command's error message or a lost connection during commit. |
| API replacement | Direct and proxy checks passed after replacement. | A changed upstream IP and uninterrupted request service were not established. |
| Locked rebuild | Installation used the runtime lock; running API image matched the built image, lock contents matched, and all 16 package pins matched. | Does not exclude extra packages or establish hash-verified artifacts. |
| Fresh development environment | Installed the 19-package development lock; dependency check and nine tests passed normally and under optimization with warnings treated as errors. | Download cache was used; not a fully uncached or clean-machine stack installation. |

The nine automated unit tests cover four API/database-failure behaviors and five
smoke-checker behaviors. Database access in those API unit tests is simulated.
Permissions, persistence, seed-conflict, and outage exercises were performed
manually; they are not nine additional automated tests or an existing CI suite.

## Resolved findings

### F01: smoke checker reported false success under optimized Python

Affected: initial Phase 1 checker before the correction, in the uncommitted
working tree. Requests were inside `assert` statements. Running
`python -O tests/smoke.py` could remove both requests and comparisons, then print
PASS without contacting the stack.

Resolution: explicit comparisons and nonzero failure results. Regression tests
passed normally and under `-O`. During a real database outage, the corrected
normal checker rejected HTTP 503 and exited with code 1 under optimized Python.

### F02: initialization error message overstated rollback certainty

Affected: initial Phase 1 database-error handler. It claimed that no changes had
committed after every caught database error. Connection loss during commit can
leave the client unsure of the outcome.

Resolution: database-error messaging now states that completion could not be
verified and warns about an unknown commit outcome. Error categories distinguish
missing configuration, fixture conflicts, and database failures. Lost-connection
and uncertain-commit paths have not been fault-injected; the wording correction
is not evidence that every such failure is handled or reconciled.

### F03: test-client dependency emitted a deprecation warning

Resolution: development requirements use `httpx2==2.15.1` rather than the old
`httpx` dependency. Nine tests passed with warnings treated as errors in normal
and optimized modes, including a fresh development-lock installation.

### F04: default startup fields caused a false deployment refusal

The initial Batch D allowlist rejected resolved API `command` and `entrypoint`
fields even when null. The owner observed a refusal before any operation was
recorded. Fix 1 accepts absent/null defaults and still rejects every non-null
startup override. The owner confirmed both defaults and passed live acceptance.
Regression tests distinguish null from empty strings/lists and actual overrides.

### F05: rejected HTTP responses were not explicitly closed

The initial Batch D worker caught HTTPError without closing its response. The
owner's Python 3.14.10 runs emitted cleanup ResourceWarnings for 302 and 503
responses even though unittest reported OK. Fix 1 closes the error response;
regression tests check closure. Both corrected owner test runs passed without
the reported warnings. An OK line alone was insufficient evidence of clean tests.

### F06 — Process exit during a test read of `/proc`

One optimized test run raised `ProcessLookupError` while reading the status of
a child process after cleanup. The process can exit between opening and reading
its `/proc` file. `tests/test_docker.py` now handles that case alongside the
already handled missing file. The test still fails if the child keeps running.
All 214 tests passed in both modes after this test-only fix.

## Current limitations and open verification gaps

- Deployment repeats targeted ownership checks under its lock. Manual Compose
  commands bypass these checks and can invalidate local operation history.
- The demo targets one Linux host and one known workload. It has no authentication,
  real health data, high-availability behavior, or continuous self-healing.
- Readiness checks table access, not complete fixture contents. The smoke checker
  expects exactly three records; additional records intentionally fail that check.
- The smoke checker has per-request socket timeouts and a response-size limit,
  but no retries or overall wall-clock deadline. Unexpected protocol errors may
  still produce a traceback rather than its concise failure format.
- The API opens a database connection per database-dependent request. Load behavior,
  connection-pool sizing, and resource limits have not been evaluated.
- API configuration is not comprehensively validated at startup. For example,
  liveness can pass with missing database configuration, while data requests fail.
- Initialization assumes the dedicated demo database. `CREATE TABLE IF NOT EXISTS`
  is not complete schema validation, and role setup does not audit arbitrary
  pre-existing grants or memberships.
- Editing `.env` alone does not rotate credentials stored in an initialized database.
  Keep existing credentials when resuming. Do not delete the volume to conceal
  an authentication problem.
- Credentials are local environment values. They are not intended for Git or
  reports, but remain accessible to sufficiently privileged Docker users.
- No application access logs are enabled by the supplied API/NGINX configuration;
  comprehensive diagnosis and bounded evidence collection remain later work.
- Digest-pinned base images and version-pinned Python packages require deliberate
  updates. Python package hashes, vulnerability auditing, and byte-identical
  builds are not established by the Phase 1 checks.
- Remote availability of every pinned image digest and a complete installation
  on a separate clean machine remain unverified. Broader OS/architecture
  compatibility is not claimed.
- Minimum memory/disk requirements, reliable startup-time bounds, and continuous
  availability have not been measured. Build output durations are not benchmarks.

The pip cache warning encountered during container inspection was avoided by
using `python -m pip --no-cache-dir ...`. There was no need to grant additional
write access. Pip's root warning during image construction does not mean the API
runs as root: the Dockerfile selects user `10001:10001` for execution. This is a
configuration fact, not a comprehensive container-security audit.

## Toolkit boundaries

- Rollback restores the application image. The database contents, configuration
  and dependencies require separate operations.
- A previously successful release may fail under changed external conditions.
- Persistent storage is not a backup. Database backup and restore are out of scope.
- Automatic recovery requires explicit opt-in and a strictly compatible
  running baseline before deployment.
- The implemented per-checkout lock coordinates participating toolkit processes,
  not external Docker commands or other checkouts.
- Local operation records are not tamper-proof audit records.
- Diagnostic observations will not always establish a root cause.
- Trusted operators, configuration, and demo images are assumed; Docker access
  does not create a security sandbox.

## Defect tracking

For each reproduced defect, record its identifier, affected version or commit,
reproduction steps, expected and observed behavior, impact, workaround, status,
and verification evidence. Label suspected defects as unconfirmed until supported.

A core acceptance failure blocks its phase. It must not be relabeled as an
acceptable limitation simply to finish. Passing the recorded checks is not
proof that no defects remain.

## Corrective batch findings after commit 7397feb

- C01: Two CLI tests read real checkout state while mocking Docker. A pending
  journal caused false test failures. They now supply explicit empty state;
  separate integration tests exercise uncertain state and Docker failure together.
- C02: Inspection timeout killed only the direct child. A descendant could keep
  running. Commands now start in a new session; cleanup kills their process group
  and bounds the direct-child wait. Tests cover timeout, exited parent and output
  overflow. This does not cancel Docker daemon work or contain escaped sessions.
- C03: Losing the first pending snapshot looked like first use because no archives
  existed. A durable marker now precedes the first pending record. A remaining
  marker without a snapshot blocks mutation. Interrupted initialization can also
  leave this conservative refusal, even though no deployment was requested.
- C04: Overview documents still described Phase 1-only behavior. Current status
  is updated while earlier acceptance results retain their historical counts.

The marker is not a backup. Removing both marker and snapshot before any archives
exist, or deleting the whole journal, can still erase evidence. Valid old-format
snapshots without markers are accepted for compatibility; missing-marker loss
cannot be distinguished from that legacy format. The next begin adds the marker
under the lock. Pending or invalid legacy snapshots remain blocked. Previously
lost legacy history cannot be reconstructed by this update.

The owner's corrective-batch tests and live stopped-API exercise passed.
The results and their boundaries are recorded in
[Phase 2 verification](PHASE-2-VERIFICATION.md).
Do not interpret this patch as proof of live deployment interruption handling.

## Batch D limitations

- The baseline is trusted local operators and trusted demo images, not execution
  of arbitrary third-party images in a security sandbox. Candidate UID/GID must
  match the demo. Image contents and entrypoint behavior are not audited here.
- Preflight observations do not lock Docker itself. External mutations may race
  with image selection, replacement and verification. Container checks sample
  states; no continuous-health or zero-downtime guarantee is made.
- Command failures, including nonzero results after partial work, conservatively
  retain pending intent. A healthy observation after timeout is not proof of a
  settled operation. This was a Phase 2 limitation. Phase 3 can explicitly close a valid pending record as unknown.
- Overall deployment time includes preflight commands, replacement, verification
  and cleanup. The verification setting is not a total deployment timeout.
- The command runner is Linux-specific (process groups and waitid). It cannot
  cancel daemon work or children that deliberately escape the process group.
- Current configuration checks cover selected demo settings and three files.
  They do not prove all live environment/configuration matches Compose, detect
  every edit-and-revert race, or support extra configuration fragments/hooks.
- The generated override is retained. Plain Compose up can restore the base
  image without toolkit recording; resume existing containers with start.
- Phase 2 records include the action and final checks. A historical record can
  only report the fields captured by that version. Refusals before pending
  intent have no operation ID.
- New version-2 snapshots require the initialization marker. Legacy version-1
  records remain readable. This is local history, not durable backup storage.

## Reconciliation and automatic recovery limits

- A stable pair of observations does not prove that work already submitted to
  the Docker daemon has settled. Confirm that separately before closing a pending
  record. A closure preserves the uncertainty about the original command result.
- Missing containers, unsupported ownership, invalid journal data and unexplained
  override mismatches can prevent closure. Restore the supported stack conditions
  and preserve the journal for diagnosis.
- The automatic path requires a strictly eligible running baseline before any
  candidate replacement. A Docker command error retains pending intent. A failed
  verification that is recorded before the process stops can remain unresolved
  by recovery when the process stops between operations.
- An older toolkit checkout can refuse a version 4 journal. Use the current
  toolkit to inspect it. The journal remains local and can be lost if its entire
  directory is removed.
- The live acceptance script schedules controlled exits before submitting a
  replacement and after Compose returns, before the toolkit records the result.
  It also builds a candidate that exits before serving HTTP. A daemon interruption
  during replacement and a live filesystem write failure require separate evidence.

## Diagnostic limits

The four observations are sequential. A connection to port 5432 shows that a
listener accepted it. PostgreSQL authentication and queries are exercised
separately through the catalogue requests. The name check uses the container's
system resolver, which may also consult a hosts file. This demo checks IPv4.

A removed container or a checkout/override mismatch can prevent inspection.
An exited API cannot run the two internal probes. If the Docker exec or HTTP
worker fails to return a recognized result, the command reports
`probe-unavailable`. A changed or unconfirmed final snapshot makes the overall
run incomplete. These observations alone cannot identify every root cause.

On the dedicated demo at Batch A commit `80bd059`, all 225 tests passed
normally and with optimization. Both catalogue routes passed before and after
diagnostics. Name resolution and TCP to port 5432 both succeeded. This was a
healthy-stack exercise.

Failure reports preserve only the first failed and last observed attempts.
An API instance observed before an HTTP request can change during that request.
Use the inspection field when interpreting route outcomes. Missing history,
a busy lock, an abrupt exit or local storage failure can prevent an export.
A previously exported file can be stale after interruption. Regenerate it by
operation ID once the journal is readable. The report contains operation,
image and container identifiers and timestamps. Review those identifiers
before sharing it. Reports give observations rather than a proven root cause.
